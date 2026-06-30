"""Pipeline：编排 L1 → L2 → L3，输出 RepoFacts。

设计要点：
- 一次 walk_files，所有阶段共用 ScanResult（避免重复 IO）；
- 每个阶段独立 try/except，单点失败不影响整体出表；
- 全程进度回调（stage/msg/pct），方便 Web 端实时显示；
- 巨型仓库友好：core.MAX_FILES + L2 TimeBudget 双重保护。

接口：
    analyze(ref, *, level="L2", on_progress=noop_progress) -> RepoFacts
    analyze_by_repo_id(repo_id, ...) -> RepoFacts
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Literal

from ..ingest.manifest import load_manifest
from ..logging import logger
from ..schemas import (
    Basics,
    BuildSystem,
    CallGraph,
    DevHistory,
    LanguageStat,
    RepoFacts,
    SyscallTable,
)
from . import l1_quick, l2_kernel, l3_signature
from .contract import RepoRef
from .core import walk_files
from .storage import save_facts

ProgressCb = Callable[[str, str, int], None]
Level = Literal["L1", "L2", "L3"]


def _noop(stage: str, msg: str, pct: int) -> None:
    return None


# ============ 主入口 ============

def analyze(
    ref: RepoRef,
    *,
    level: Level = "L2",
    on_progress: ProgressCb = _noop,
    persist: bool = True,
    l2_budget_seconds: float = 30.0,
) -> RepoFacts:
    """对单个仓库执行 L1/L2/L3 分析，返回 RepoFacts。

    Args:
        ref: 要分析的仓库（local_path 必须存在）。
        level: 分析深度。L1=秒级，L2=数十秒，L3=可能更长。
        on_progress: 进度回调。
        persist: 是否落盘到 data/facts/<repo_id>.json。
        l2_budget_seconds: L2 函数索引时间预算。
    """
    root = Path(ref.local_path)
    if not root.exists():
        raise FileNotFoundError(f"仓库目录不存在: {root}")

    t_start = time.time()
    on_progress("init", f"开始 {level} 分析 {ref.repo_id}", 0)

    # ---------- Stage 0: walk ----------
    on_progress("walk", "扫描文件树", 5)
    scan = walk_files(root)
    on_progress(
        "walk",
        f"扫描完成：{len(scan.files)} 个文件 "
        f"({'已截断' if scan.truncated else 'OK'}, {scan.elapsed:.1f}s)",
        15,
    )

    # ---------- Stage 1: L1 ----------
    on_progress("l1", "L1 QuickProfile（语言/架构/构建/模板/git）", 20)
    try:
        basics, dev_hist = l1_quick.run(scan)
    except Exception as e:
        logger.exception(f"L1 失败: {e}")
        on_progress("l1", f"L1 失败（已降级）: {e}", 35)
        basics, dev_hist = _empty_basics(), _empty_history()
    on_progress(
        "l1",
        f"L1 完成：{len(basics.languages)} 种语言, "
        f"{basics.total_loc} loc, arch={basics.arch}, build={basics.build.kind}",
        45,
    )

    # ---------- Stage 2: L2 ----------
    if level in ("L2", "L3"):
        on_progress("l2", "L2 KernelInsight（子系统/syscall/函数节点）", 50)
        try:
            subsystems, syscalls, cg = l2_kernel.run(scan, budget_seconds=l2_budget_seconds)
        except Exception as e:
            logger.exception(f"L2 失败: {e}")
            on_progress("l2", f"L2 失败（已降级）: {e}", 70)
            subsystems, syscalls, cg = [], SyscallTable(count=0, items=[]), CallGraph(nodes=[], edges_count=0)
        on_progress(
            "l2",
            f"L2 完成：{len(subsystems)} 子系统, "
            f"{syscalls.count} syscall, {len(cg.nodes)} 函数节点",
            80,
        )
    else:
        subsystems = []
        syscalls = SyscallTable(count=0, items=[])
        cg = CallGraph(nodes=[], edges_count=0)

    # ---------- Stage 3: L3 ----------
    if level == "L3":
        on_progress("l3", "L3 StructuralSignature（MinHash）", 85)
        try:
            sig = l3_signature.run(scan, cg)
        except Exception as e:
            logger.exception(f"L3 失败: {e}")
            sig = None
        if sig:
            cg.minhash_signature = sig
            on_progress("l3", f"L3 完成：签名长度 {len(sig)}", 90)
        else:
            on_progress("l3", "L3 跳过（datasketch 未安装或签名为空）", 90)

    # ---------- 拼装 RepoFacts ----------
    on_progress("assemble", "拼装事实表", 95)
    facts = RepoFacts(
        repo_id=ref.repo_id,
        head_commit=ref.head_commit or "",
        basics=basics,
        kernel_features=subsystems,
        syscalls=syscalls,
        call_graph=cg,
        dev_history=dev_hist,
        summary_for_embedding=_build_summary(ref.repo_id, basics, subsystems, syscalls),
    )

    if persist:
        path = save_facts(facts)
        on_progress("save", f"已写入 {path}", 99)

    elapsed = time.time() - t_start
    on_progress("done", f"完成 ({elapsed:.1f}s)", 100)
    logger.info(f"analyze {ref.repo_id} done in {elapsed:.1f}s (level={level})")
    return facts


def analyze_by_repo_id(
    repo_id: str,
    *,
    level: Level = "L2",
    on_progress: ProgressCb = _noop,
    persist: bool = True,
    l2_budget_seconds: float = 30.0,
) -> RepoFacts:
    """从 manifest 中查到 local_path，再调 analyze()。"""
    m = load_manifest()
    entry = next((r for r in m.repos if r.repo_id == repo_id), None)
    if entry is None:
        raise ValueError(f"repo_id 未在 manifest 中: {repo_id}")
    if not entry.local_path:
        raise ValueError(f"repo {repo_id} 尚未克隆 (status={entry.status.value})")
    ref = RepoRef(
        repo_id=entry.repo_id,
        local_path=entry.local_path,
        head_commit=entry.head_commit,
    )
    return analyze(
        ref,
        level=level,
        on_progress=on_progress,
        persist=persist,
        l2_budget_seconds=l2_budget_seconds,
    )


# ============ 辅助 ============

def _empty_basics() -> Basics:
    return Basics(
        languages=[],
        total_loc=0,
        arch=["other"],
        build=BuildSystem(kind="unknown", files=[]),
        base_template=None,
        base_template_evidence=[],
    )


def _empty_history() -> DevHistory:
    return DevHistory(commits_total=0, contributors_total=0, milestones=[])


def _build_summary(
    repo_id: str,
    basics: Basics,
    subsystems: list,
    syscalls: SyscallTable,
) -> str:
    """生成 RAG embedding 用的文本摘要（非 LLM）。"""
    lang_txt = ", ".join(
        f"{s.language}({s.percent:.1f}%)" for s in basics.languages[:5]
    ) or "未知"
    sub_txt = ", ".join(sorted({s.feature for s in subsystems})) or "未识别"
    tpl_txt = basics.base_template or "未识别"
    return (
        f"仓库 {repo_id}: 语言占比 {lang_txt}; 总 LOC {basics.total_loc}; "
        f"架构 {','.join(basics.arch)}; 构建 {basics.build.kind}; "
        f"基线模板 {tpl_txt}; "
        f"识别子系统 [{sub_txt}]; "
        f"syscall 数 {syscalls.count}."
    )
