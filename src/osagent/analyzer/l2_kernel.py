"""L2 KernelInsight：内核子系统定位 + syscall 抽取 + 函数节点索引。

性能与正确性：
- 只对源代码文件做（SOURCE_EXTS）；
- 单文件 size 截断（safe_read）；
- 全程 O(N)，每个源文件最多被读 1 次；
- 设置硬上限：函数节点数 / 子系统每项 hit 数。
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from ..logging import logger
from ..schemas import (
    CallGraph,
    Evidence,
    FunctionNode,
    KernelFeature,
    Syscall,
    SyscallTable,
)
from .core import SOURCE_EXTS, ScanResult, TimeBudget, safe_read

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

# 正则（注意：避免 [\w\s\*]* 这种回溯重灾区；只匹配"行首 标识符 ( ... ) {"）
RUST_FN_PATTERN = re.compile(
    r"^\s{0,8}(?:pub(?:\([^)]{0,40}\))?\s+)?(?:async\s+)?(?:unsafe\s+)?"
    r"(?:extern\s+\"[^\"]{1,16}\"\s+)?fn\s+([a-zA-Z_][a-zA-Z0-9_]{0,64})\s*[<(]",
    re.MULTILINE,
)
# C 函数：扫"行首一个标识符序列后跟 ( ... ) {"。最后一个标识符就是函数名。
# 用非贪婪 + 字符上限避免灾难回溯。
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


# ========== 子系统 ==========

def _detect_subsystems(scan: ScanResult) -> list[KernelFeature]:
    """按路径关键字命中识别子系统。"""
    features: list[KernelFeature] = []
    for subsys, hints in SUBSYSTEM_HINTS.items():
        matched: list[str] = []
        evidence: list[Evidence] = []
        for f in scan.files:
            if not f.is_source:
                continue
            rel_l = f.rel.lower()
            if any(h in rel_l for h in hints):
                matched.append(f.rel)
                if len(evidence) < 3:
                    evidence.append(Evidence(file=f.rel, start_line=1, end_line=50))
                if len(matched) >= MAX_SUBSYS_FILES:
                    break
        if matched:
            features.append(
                KernelFeature(
                    feature=subsys,  # type: ignore[arg-type]
                    description=f"基于源码路径命中识别（命中 {len(matched)} 个源文件）",
                    implementation="（需 LLM 阅读源码后给出具体实现方式）",
                    files=matched[:10],
                    evidence=evidence,
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
            syscalls[name] = Syscall(
                name=name,
                handler_file=f.rel,
                handler_func=name,
                evidence=Evidence(file=f.rel, start_line=line_no, end_line=line_no + 5),
            )
            if len(syscalls) >= MAX_SYSCALLS:
                break

        if dispatcher_file is None and DISPATCHER_PATTERN.search(text):
            dispatcher_file = f.rel

    items = sorted(syscalls.values(), key=lambda s: s.name)
    return SyscallTable(count=len(items), items=items, dispatcher_file=dispatcher_file)


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


# ========== 顶层 ==========

def run(scan: ScanResult, *, budget_seconds: float = 30.0) -> tuple[list[KernelFeature], SyscallTable, CallGraph]:
    """L2：子系统 + syscall + 函数节点（不算调用边）。

    budget_seconds 在 syscall 抽取和函数索引之间近似平均分配（各 ~50%）。
    """
    logger.debug(f"L2 start, budget={budget_seconds}s")

    subsystems = _detect_subsystems(scan)
    sc_budget = TimeBudget(budget_seconds * 0.4)
    syscalls = _extract_syscalls(scan, sc_budget)
    fn_budget = TimeBudget(budget_seconds * 0.6)
    fn_nodes = _list_functions(scan, fn_budget)

    cg = CallGraph(nodes=fn_nodes, edges_count=0)  # edges 留给 L3
    return subsystems, syscalls, cg
