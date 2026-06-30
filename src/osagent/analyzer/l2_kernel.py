"""L2 KernelInsight：内核子系统定位 + syscall 抽取 + 函数节点索引。

性能与正确性：
- 只对源代码文件做（SOURCE_EXTS）；
- 单文件 size 截断（safe_read）；
- 全程 O(N)，每个源文件最多被读 1 次；
- 设置硬上限：函数节点数 / 子系统每项 hit 数。

v1.1 新增：
- 每个子系统抽 key_functions / data_structures / feature_tags / code_excerpts
- syscall 走 syscall_dict 分类 + 描述
- evidence 不再永远是 1-50，而是真实命中行号
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from ..logging import logger
from ..schemas import (
    CallGraph,
    CodeExcerpt,
    Evidence,
    FunctionNode,
    KernelFeature,
    Syscall,
    SyscallTable,
)
from .core import SOURCE_EXTS, ScanResult, TimeBudget, safe_read
from .feature_tags import detect_tags_for_feature
from .syscall_dict import CATEGORY_ORDER, classify as classify_syscall

# ========== 常量 ==========

# 子系统关键字（路径子串匹配；越长越具体）
SUBSYSTEM_HINTS: dict[str, list[str]] = {
    "scheduler": ["sched", "scheduler", "run_queue", "task_manager"],
    "memory": ["frame_alloc", "heap_alloc", "buddy", "slab", "page_table",
               "address_space", "mm/", "/mm.rs", "memory.rs"],
    "process": ["proc/", "process.", "task/", "thread.", "/task.rs"],
    "syscall": ["syscall", "sys_call"],
    "filesystem": ["fs/", "fat32", "ext2", "vfs", "easyfs", "ffs",
                   "inode", "dentry"],
    "driver": ["drivers/", "/driver.", "virtio", "sdcard", "uart",
               "/plic.", "ns16550"],
    "ipc": ["pipe.", "/signal.", "shm.", "mutex.", "semaphore."],
    "smp": ["smp/", "multi_core", "multicore", "harts", "cpu_id"],
    "trap": ["trap.", "interrupt.", "/irq.", "exception."],
    "boot": ["boot/", "entry.s", "entry.S", "/start.s", "linker.ld"],
    "virtio": ["virtio"],
    "network": ["/net/", "/tcp.", "/udp.", "lwip"],
}

MAX_FN_NODES = 3000
MAX_SYSCALLS = 500
MAX_SUBSYS_FILES = 30

# 每个子系统抽多少 key_functions / data_structures / code_excerpts
PER_FEATURE_TOP_FUNCS = 8
PER_FEATURE_TOP_STRUCTS = 8
PER_FEATURE_CODE_EXCERPTS = 2
EXCERPT_MAX_LINES = 30  # 每个片段最多展示 30 行

# 正则（注意：避免 [\w\s\*]* 这种回溯重灾区；只匹配"行首 标识符 ( ... ) {"）
RUST_FN_PATTERN = re.compile(
    r"^\s{0,8}(?:pub(?:\([^)]{0,40}\))?\s+)?(?:async\s+)?(?:unsafe\s+)?"
    r"(?:extern\s+\"[^\"]{1,16}\"\s+)?fn\s+([a-zA-Z_][a-zA-Z0-9_]{0,64})\s*[<(]",
    re.MULTILINE,
)
# C 函数：扫"行首一个标识符序列后跟 ( ... ) {"。最后一个标识符就是函数名。
C_FN_PATTERN = re.compile(
    r"^(?:[a-zA-Z_][a-zA-Z_0-9]{0,63}[\s\*]{1,8}){1,5}"
    r"([a-zA-Z_][a-zA-Z_0-9]{0,63})\s*\([^;{}\n]{0,300}\)\s*\{",
    re.MULTILINE,
)
SYSCALL_FN_RUST = re.compile(
    r"(?:pub\s+)?fn\s+(sys_[a-z0-9_]+)\s*\(", re.I
)
SYSCALL_FN_C = re.compile(
    r"\b(?:int|long|ssize_t|void|uint64|size_t)\s+(sys_[a-z0-9_]+)\s*\(", re.I
)
DISPATCHER_PATTERN = re.compile(
    r"(?:match\s+\w+\s*\{[\s\S]{0,300}?sys_)|"
    r"(?:switch\s*\(\s*\w+\s*\)\s*\{[\s\S]{0,300}?case\s+SYS)"
)

# 数据结构正则
RUST_STRUCT_PATTERN = re.compile(
    r"^\s{0,8}(?:pub(?:\([^)]{0,40}\))?\s+)?"
    r"(?:struct|enum|union)\s+([A-Z][A-Za-z0-9_]{0,63})\b",
    re.MULTILINE,
)
C_STRUCT_PATTERN = re.compile(
    r"^\s{0,8}(?:typedef\s+)?(?:struct|union|enum)\s+([a-zA-Z_][A-Za-z0-9_]{0,63})\b",
    re.MULTILINE,
)


# ========== 子系统 ==========

def _detect_subsystems(scan: ScanResult) -> list[KernelFeature]:
    """按路径关键字命中识别子系统（仅记录命中文件，留待 _enrich_features 二次扫）。"""
    features: list[KernelFeature] = []
    for subsys, hints in SUBSYSTEM_HINTS.items():
        matched: list[str] = []
        for f in scan.files:
            if not f.is_source:
                continue
            rel_l = f.rel.lower()
            if any(h in rel_l for h in hints):
                matched.append(f.rel)
                if len(matched) >= MAX_SUBSYS_FILES:
                    break
        if matched:
            features.append(
                KernelFeature(
                    feature=subsys,  # type: ignore[arg-type]
                    description=f"基于源码路径命中识别（命中 {len(matched)} 个源文件）",
                    implementation="（详见 key_functions / feature_tags）",
                    files=matched[:10],
                    evidence=[],  # 留待 _enrich 填真证据
                    confidence="medium",
                )
            )
    return features


# ========== Syscall ==========

# secondary 文件数硬上限（防巨型仓库爆）
MAX_SECONDARY_FILES = 400


def _extract_syscalls(scan: ScanResult, budget: TimeBudget) -> SyscallTable:
    syscalls: dict[str, Syscall] = {}
    dispatcher_file: str | None = None

    # 优先扫名字像 syscall 的文件（O(n)，用 set 标记）
    primary: list = []
    primary_ids: set[int] = set()
    for f in scan.files:
        if f.is_source and "syscall" in f.rel.lower():
            primary.append(f)
            primary_ids.add(id(f))

    # secondary: 排除 primary，按"路径含 sys_/kernel/proc/trap"做粗筛
    KEYS = ("sys_", "kernel/", "proc/", "process.", "trap.", "/main.", "irq.")
    secondary: list = []
    for f in scan.files:
        if not f.is_source or id(f) in primary_ids:
            continue
        rel_l = f.rel.lower()
        if any(k in rel_l for k in KEYS):
            secondary.append(f)
            if len(secondary) >= MAX_SECONDARY_FILES:
                break

    for f in primary + secondary:
        if len(syscalls) >= MAX_SYSCALLS:
            break
        if budget.should_stop():
            logger.warning(
                f"L2.syscalls: 超时 {budget.budget}s，提前停止（已收集 {len(syscalls)}）"
            )
            break
        text = safe_read(f.path)
        if not text:
            continue

        pat = SYSCALL_FN_RUST if f.ext == ".rs" else SYSCALL_FN_C
        for m in pat.finditer(text):
            name = m.group(1)
            if name in syscalls:
                continue
            line_no = text[: m.start()].count("\n") + 1
            cat, desc = classify_syscall(name)
            syscalls[name] = Syscall(
                name=name,
                handler_file=f.rel,
                handler_func=name,
                evidence=Evidence(file=f.rel, start_line=line_no, end_line=line_no + 5),
                category=cat,
                description=desc,
            )
            if len(syscalls) >= MAX_SYSCALLS:
                break

        if dispatcher_file is None and DISPATCHER_PATTERN.search(text):
            dispatcher_file = f.rel

    items = sorted(syscalls.values(), key=lambda s: s.name)
    # 分类计数
    by_cat: dict[str, int] = {c: 0 for c in CATEGORY_ORDER}
    for s in items:
        by_cat[s.category] = by_cat.get(s.category, 0) + 1
    return SyscallTable(
        count=len(items),
        items=items,
        dispatcher_file=dispatcher_file,
        by_category={k: v for k, v in by_cat.items() if v > 0},
    )


# ========== Functions ==========

# 单文件超过这个大小，不做函数正则（巨型生成代码 / amalgamation 防爆）
_FN_FILE_MAX_BYTES = 200_000


def _list_functions(scan: ScanResult, budget: TimeBudget) -> list[FunctionNode]:
    nodes: list[FunctionNode] = []
    for f in scan.files:
        if budget.should_stop():
            logger.warning(
                f"L2.functions: 超时 {budget.budget}s，提前停止（已收集 {len(nodes)}）"
            )
            break
        if f.ext not in {".rs", ".c", ".cpp", ".cc"}:
            continue
        if f.size > _FN_FILE_MAX_BYTES:
            continue
        text = safe_read(f.path, max_bytes=_FN_FILE_MAX_BYTES)
        if not text:
            continue
        pat = RUST_FN_PATTERN if f.ext == ".rs" else C_FN_PATTERN
        try:
            matches = list(pat.finditer(text))
        except Exception:  # 极端回溯 / 内存异常
            continue
        for m in matches:
            line_no = text[: m.start()].count("\n") + 1
            nodes.append(
                FunctionNode(
                    qualified_name=f"{f.rel}:{m.group(1)}",
                    file=f.rel,
                    start_line=line_no,
                    end_line=line_no,
                    in_degree=0,
                    out_degree=0,
                )
            )
            if len(nodes) >= MAX_FN_NODES:
                logger.debug(f"L2.functions: 达上限 {MAX_FN_NODES}，停止")
                return nodes
    return nodes


# ========== Enrich: key_functions / data_structures / feature_tags / code_excerpts ==========

# 不感兴趣的"通用 helper"函数名（避免噪音）
_BORING_FN_NAMES = {
    "new", "default", "from", "into", "fmt", "clone", "drop", "deref",
    "deref_mut", "as_ref", "as_mut", "eq", "hash", "len", "is_empty",
    "main", "init", "test", "tests",
}

# 不感兴趣的 struct（Rust trait impl 常见噪声）
_BORING_STRUCT_NAMES = {
    "T", "U", "E", "Item", "Output", "Error", "Result", "Ok", "Err",
}


def _enrich_features(
    features: list[KernelFeature],
    fn_nodes: list[FunctionNode],
    scan: ScanResult,
) -> None:
    """在原地为每个 KernelFeature 填 key_functions / data_structures / feature_tags / code_excerpts / evidence。"""
    # 文件 -> [函数节点]
    fn_by_file: dict[str, list[FunctionNode]] = defaultdict(list)
    for n in fn_nodes:
        fn_by_file[n.file].append(n)

    # 文件 -> FileItem（用于读 path）
    file_by_rel: dict[str, object] = {f.rel: f for f in scan.files}

    for kf in features:
        files_set = set(kf.files)

        # ---- key_functions ----
        # 收集该子系统所有命中文件的函数，去重 boring，取 top N（按函数名长度作粗略权重，"sys_xxx"/"do_xxx" 类更长更具体）
        seen_fn: set[str] = set()
        ranked_fn: list[tuple[str, str, int]] = []  # (name, file, start_line)
        for rel in kf.files:
            for n in fn_by_file.get(rel, []):
                name = n.qualified_name.split(":")[-1]
                if name in _BORING_FN_NAMES or len(name) < 3:
                    continue
                if name in seen_fn:
                    continue
                seen_fn.add(name)
                ranked_fn.append((name, n.file, n.start_line))
        # 简单排序：含 sys_/do_/handle_/init_/alloc_/free_ 前缀的优先
        def _rank(name: str) -> int:
            for i, p in enumerate(
                ("sys_", "do_", "handle_", "init_", "alloc_", "free_", "schedule", "trap", "kmain"),
            ):
                if name.startswith(p) or p in name:
                    return -10 + i  # 越靠前优先级越高（小越优先）
            return len(name)  # 名字越长越具体
        ranked_fn.sort(key=lambda t: _rank(t[0]))
        kf.key_functions = [t[0] for t in ranked_fn[:PER_FEATURE_TOP_FUNCS]]

        # ---- data_structures ----
        structs: list[str] = []
        seen_st: set[str] = set()
        for rel in kf.files[:8]:
            fi = file_by_rel.get(rel)
            if fi is None:
                continue
            text = safe_read(fi.path, max_bytes=200_000)
            if not text:
                continue
            pat = RUST_STRUCT_PATTERN if fi.ext == ".rs" else C_STRUCT_PATTERN
            try:
                for m in pat.finditer(text):
                    name = m.group(1)
                    if name in _BORING_STRUCT_NAMES or name in seen_st or len(name) < 3:
                        continue
                    seen_st.add(name)
                    structs.append(name)
                    if len(structs) >= PER_FEATURE_TOP_STRUCTS:
                        break
            except Exception:
                continue
            if len(structs) >= PER_FEATURE_TOP_STRUCTS:
                break
        kf.data_structures = structs

        # ---- feature_tags ----
        kf.feature_tags = detect_tags_for_feature(kf.feature, kf.files, scan.root)

        # ---- code_excerpts + evidence ----
        # 选 ranked_fn 的前 PER_FEATURE_CODE_EXCERPTS 个，去文件里抠出函数体（最多 30 行）
        excerpts: list[CodeExcerpt] = []
        new_evidence: list[Evidence] = []
        for name, rel, start_line in ranked_fn[:PER_FEATURE_CODE_EXCERPTS]:
            fi = file_by_rel.get(rel)
            if fi is None:
                continue
            text = safe_read(fi.path, max_bytes=200_000)
            if not text:
                continue
            snippet, end_line = _extract_snippet(text, start_line, EXCERPT_MAX_LINES)
            if not snippet:
                continue
            lang = "rust" if fi.ext == ".rs" else "c"
            excerpts.append(
                CodeExcerpt(
                    file=rel,
                    start_line=start_line,
                    end_line=end_line,
                    code=snippet,
                    lang=lang,
                    caption=f"`{name}` 函数实现",
                )
            )
            new_evidence.append(
                Evidence(file=rel, start_line=start_line, end_line=end_line)
            )

        # 兜底 evidence：用 data_structures 的位置（再不行就用文件首部）
        if not new_evidence and kf.files:
            new_evidence.append(Evidence(file=kf.files[0], start_line=1, end_line=20))

        kf.code_excerpts = excerpts
        kf.evidence = new_evidence

        # 改善 description：拼上前 3 个 feature_tags
        if kf.feature_tags:
            kf.description = (
                f"命中 {len(kf.files)} 个源文件，识别特征："
                + "、".join(kf.feature_tags[:5])
            )
        # implementation：用 key_functions 拼一句
        if kf.key_functions:
            kf.implementation = "关键函数：" + ", ".join(f"`{n}`" for n in kf.key_functions[:5])


def _extract_snippet(text: str, start_line: int, max_lines: int) -> tuple[str, int]:
    """从 text 第 start_line 开始抠出最多 max_lines 行的代码片段，尝试在花括号配平处截断。"""
    lines = text.splitlines()
    if start_line <= 0 or start_line > len(lines):
        return "", start_line

    # 简单花括号配平：从 start_line 起，找到第一个 { 后追踪，遇到 } 计数归 0 就停
    snippet_lines: list[str] = []
    depth = 0
    started = False
    for i in range(start_line - 1, min(start_line - 1 + max_lines, len(lines))):
        line = lines[i]
        snippet_lines.append(line)
        for ch in line:
            if ch == "{":
                depth += 1
                started = True
            elif ch == "}":
                depth -= 1
        if started and depth <= 0:
            break
    end_line = start_line + len(snippet_lines) - 1
    # 去除前置/末尾空行 + 截长行（避免巨长行撑爆 markdown）
    safe = [ln if len(ln) <= 200 else ln[:200] + " ..." for ln in snippet_lines]
    return "\n".join(safe), end_line


# ========== 顶层 ==========

def run(scan: ScanResult, *, budget_seconds: float = 30.0) -> tuple[list[KernelFeature], SyscallTable, CallGraph]:
    """L2：子系统 + syscall + 函数节点 + 子系统富化。

    budget_seconds 在 syscall 抽取和函数索引之间近似平均分配（各 ~50%）。
    """
    logger.debug(f"L2 start, budget={budget_seconds}s")

    subsystems = _detect_subsystems(scan)
    sc_budget = TimeBudget(budget_seconds * 0.35)
    syscalls = _extract_syscalls(scan, sc_budget)
    fn_budget = TimeBudget(budget_seconds * 0.45)
    fn_nodes = _list_functions(scan, fn_budget)

    # v1.1：富化子系统
    try:
        _enrich_features(subsystems, fn_nodes, scan)
    except Exception as e:
        logger.exception(f"L2.enrich 失败（已降级）: {e}")

    cg = CallGraph(nodes=fn_nodes, edges_count=0)  # edges 留给 L3
    return subsystems, syscalls, cg
