"""检索器：把"问题 + scope"转换成一组 QAContextItem。

不依赖任何 LLM，纯关键字匹配 + 事实表字段挑选。

策略：
- repo scope：
  * 总是放入 [基本面] 卡片
  * 按问题中的中文/英文关键词命中的子系统（最多 3 个），把它们的 description / implementation
    / key_functions / data_structures / feature_tags / code_excerpts 装进去
  * 若问题提到 syscall / 系统调用 / 调用号，附加 [syscall 表] 摘要
  * 若问题提到"开发 / 历史 / 提交 / 贡献者"，附加 [开发历史]
  * 若问题提到"目录 / 结构"，附加 [目录结构]（≤30 行）
  * 兜底：至少给一条 [项目总览]

- compare scope：
  * 总是放入 [基本面 diff]、[相似度评分]、[亮点/差异 摘要]
  * 按问题命中子系统，挨个把 SubsystemDiff 装进去
  * 若涉及 syscall，附加 [syscall diff]

- global scope：v2 才做，目前返回空列表 + 一条 warning。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ..analyzer import has_facts, load_facts
from ..config import settings
from ..report import (
    compare_json_path,
    has_compare_json,
)
from ..schemas import CompareReport, RepoFacts
from ..schemas.qa import QAContextItem, QARequest, QASource

# ---------------- 关键词字典 ----------------

# 中文 / 英文同义词 → 标准 KernelFeature.feature
_KEYWORD_TO_FEATURE: dict[str, str] = {
    # boot
    "boot": "boot", "启动": "boot", "引导": "boot", "bootloader": "boot",
    "entry": "boot", "head.s": "boot",
    # memory
    "memory": "memory", "内存": "memory", "mm": "memory", "mmu": "memory",
    "页表": "memory", "分页": "memory", "buddy": "memory", "slab": "memory",
    "heap": "memory", "vma": "memory", "frame": "memory", "alloc": "memory",
    # scheduler
    "scheduler": "scheduler", "sched": "scheduler", "调度": "scheduler",
    "cfs": "scheduler", "round-robin": "scheduler", "时间片": "scheduler",
    # process
    "process": "process", "进程": "process", "task": "process", "pcb": "process",
    "thread": "process", "线程": "process", "fork": "process", "exec": "process",
    # syscall
    "syscall": "syscall", "系统调用": "syscall", "syscalls": "syscall",
    "trap_handler": "syscall", "trap handler": "syscall",
    # filesystem / vfs
    "filesystem": "filesystem", "fs": "filesystem", "文件系统": "filesystem",
    "ext": "filesystem", "fat": "filesystem", "inode": "filesystem",
    "vfs": "vfs", "虚拟文件系统": "vfs",
    # driver
    "driver": "driver", "驱动": "driver", "virtio": "virtio",
    "uart": "driver", "console": "driver", "块设备": "driver",
    # ipc
    "ipc": "ipc", "进程通信": "ipc", "capability": "ipc", "pipe": "ipc",
    "shm": "ipc", "shared memory": "ipc",
    # smp
    "smp": "smp", "多核": "smp", "多处理器": "smp", "spinlock": "smp",
    # network
    "network": "network", "网络": "network", "tcp": "network", "ip": "network",
    "lwip": "network", "smoltcp": "network",
    # signal
    "signal": "signal", "信号": "signal",
    # trap
    "trap": "trap", "异常": "trap", "中断": "trap", "interrupt": "trap",
    "plic": "trap", "clint": "trap", "scause": "trap",
}

# 这些关键字出现 → 把对应"附加块"打开
_NEEDS_SYSCALL_TABLE = {"syscall", "系统调用", "调用号", "sys_", "ecall"}
_NEEDS_DEV_HISTORY = {"开发", "历史", "提交", "贡献者", "commit", "contributor", "milestone", "里程碑"}
_NEEDS_DIRECTORY = {"目录", "结构", "directory", "layout", "tree"}


def _hit_features(question: str) -> list[str]:
    """从问题里挑出 ≤3 个最相关的 KernelFeature.feature。"""
    q = question.lower()
    hits: list[str] = []
    for kw, feat in _KEYWORD_TO_FEATURE.items():
        if kw in q and feat not in hits:
            hits.append(feat)
        if len(hits) >= 3:
            break
    return hits


def _need_any(question: str, keys: set[str]) -> bool:
    ql = question.lower()
    return any(k.lower() in ql for k in keys)


def _est_tokens(text: str) -> int:
    # 粗略：中文 1 字 ≈ 1 token；英文 1 token ≈ 4 字符。这里折中按 chars/2。
    return max(1, len(text) // 2)


# ---------------- 文本化 helpers ----------------

def _fmt_basics_block(facts: RepoFacts) -> str:
    b = facts.basics
    langs = ", ".join(f"{l.language} {l.percent:.0f}%" for l in b.languages[:5])
    arch = ", ".join(b.arch) if b.arch else "未知"
    tpl = b.base_template or "未识别"
    return (
        f"- 主要语言: {langs or '未识别'}\n"
        f"- 架构: {arch}\n"
        f"- 构建系统: {b.build.kind}\n"
        f"- 基线模板: {tpl}\n"
        f"- 代码行数(LOC): {b.total_loc}\n"
        f"- HEAD commit: {facts.head_commit[:12]}"
    )


def _fmt_subsystem_block(kf) -> str:  # noqa: ANN001
    lines = [
        f"- 实现方式: {kf.implementation or '未知'}",
        f"- 描述: {kf.description or '（无）'}",
        f"- 置信度: {kf.confidence}",
        f"- 涉及文件数: {len(kf.files)}",
    ]
    if kf.key_functions:
        lines.append(f"- 关键函数: {', '.join(kf.key_functions[:10])}")
    if kf.data_structures:
        lines.append(f"- 关键数据结构: {', '.join(kf.data_structures[:10])}")
    if kf.feature_tags:
        lines.append(f"- 功能标签: {', '.join(kf.feature_tags[:8])}")
    if kf.code_excerpts:
        ex = kf.code_excerpts[0]
        snippet = "\n".join(ex.code.splitlines()[:18])
        lines.append(
            f"- 代表代码 ({ex.file}:{ex.start_line}-{ex.end_line}):\n```{ex.lang}\n{snippet}\n```"
        )
    return "\n".join(lines)


def _fmt_syscalls_block(facts: RepoFacts) -> str:
    s = facts.syscalls
    by_cat = ", ".join(f"{k}={v}" for k, v in sorted(s.by_category.items()))
    sample = ", ".join(item.name for item in s.items[:20])
    return (
        f"- 总数: {s.count}\n"
        f"- 分类统计: {by_cat or '（无）'}\n"
        f"- dispatcher 文件: {s.dispatcher_file or '未识别'}\n"
        f"- 示例名: {sample}"
    )


def _fmt_dev_history_block(facts: RepoFacts) -> str:
    d = facts.dev_history
    first = d.first_commit_at.isoformat() if d.first_commit_at else "?"
    last = d.last_commit_at.isoformat() if d.last_commit_at else "?"
    ms = "; ".join(f"{c.timestamp.date()} {c.message_first_line[:40]}" for c in d.milestones[:5])
    return (
        f"- 提交总数: {d.commits_total}\n"
        f"- 贡献者数: {d.contributors_total}\n"
        f"- 首次提交: {first}\n"
        f"- 最近提交: {last}\n"
        f"- 里程碑: {ms or '（无）'}"
    )


def _fmt_directory_block(facts: RepoFacts) -> str:
    if not facts.directory_tree:
        return "（无目录树）"
    lines: list[str] = []

    def walk(node, depth: int):
        if depth > 2:
            return
        prefix = "  " * depth + ("📁 " if node.kind == "dir" else "📄 ")
        suffix = f" ({node.loc} LOC)" if node.loc else ""
        lines.append(f"{prefix}{node.name}{suffix}")
        for ch in node.children[:8]:
            walk(ch, depth + 1)

    walk(facts.directory_tree, 0)
    return "\n".join(lines[:40])


def _fmt_summary_block(facts: RepoFacts) -> str:
    parts: list[str] = []
    if facts.project_summary:
        parts.append("项目总结:")
        parts.extend(f"  * {x}" for x in facts.project_summary[:8])
    if facts.tech_highlights:
        parts.append("技术亮点:")
        for h in facts.tech_highlights[:4]:
            parts.append(f"  * [{h.title}] {h.summary}")
    if not parts:
        parts.append(facts.summary_for_embedding[:300] or "（暂无总结）")
    return "\n".join(parts)


# ---------------- 顶层入口 ----------------

def retrieve(req: QARequest) -> tuple[list[QAContextItem], list[str]]:
    """返回 (items, warnings)。"""
    if req.scope == "repo":
        return _retrieve_repo(req)
    if req.scope == "compare":
        return _retrieve_compare(req)
    return [], ["scope=global 尚未实现，请改用 repo 或 compare。"]


# ---------- repo ----------

def _retrieve_repo(req: QARequest) -> tuple[list[QAContextItem], list[str]]:
    warns: list[str] = []
    if not req.repo_id:
        return [], ["scope=repo 必须提供 repo_id"]
    if not has_facts(req.repo_id):
        return [], [f"事实表不存在: {req.repo_id}，请先 POST /api/repos/{{id}}/analyze"]

    facts = load_facts(req.repo_id)
    items: list[QAContextItem] = []

    # 1) 基本面
    body = _fmt_basics_block(facts)
    items.append(QAContextItem(
        title=f"[基本面] {facts.repo_id}",
        body=body,
        source=QASource(
            type="facts_field", repo_id=facts.repo_id,
            label=f"{facts.repo_id} · 基本面",
            detail=f"语言 / 架构 / 构建 / 基线 / LOC",
            anchor="basics",
        ),
        tokens_est=_est_tokens(body),
    ))

    # 2) 项目总览（兜底命中）
    body = _fmt_summary_block(facts)
    items.append(QAContextItem(
        title=f"[项目总览] {facts.repo_id}",
        body=body,
        source=QASource(
            type="facts_field", repo_id=facts.repo_id,
            label=f"{facts.repo_id} · 项目总览",
            detail="project_summary + tech_highlights",
            anchor="project_summary",
        ),
        tokens_est=_est_tokens(body),
    ))

    # 3) 按问题命中子系统
    feature_hits = _hit_features(req.question)
    if feature_hits:
        kf_by_feat = {kf.feature: kf for kf in facts.kernel_features}
        for feat in feature_hits:
            kf = kf_by_feat.get(feat)
            if not kf:
                warns.append(f"问题命中子系统 {feat}，但该仓库未识别该子系统。")
                continue
            body = _fmt_subsystem_block(kf)
            ev_file = kf.code_excerpts[0].file if kf.code_excerpts else (kf.files[0] if kf.files else None)
            ev_start = kf.code_excerpts[0].start_line if kf.code_excerpts else None
            ev_end = kf.code_excerpts[0].end_line if kf.code_excerpts else None
            items.append(QAContextItem(
                title=f"[子系统:{feat}] {facts.repo_id}",
                body=body,
                source=QASource(
                    type="subsystem", repo_id=facts.repo_id,
                    label=f"{facts.repo_id} · 子系统 {feat}",
                    detail=kf.implementation or "",
                    file=ev_file, start_line=ev_start, end_line=ev_end,
                    anchor=f"kernel_features.{feat}",
                ),
                tokens_est=_est_tokens(body),
            ))
    else:
        # 没命中：附上所有子系统的一句话清单
        body_lines = [f"- {kf.feature}: {kf.implementation or kf.description or ''}"
                      for kf in facts.kernel_features]
        body = "\n".join(body_lines) or "（未识别任何子系统）"
        items.append(QAContextItem(
            title=f"[子系统清单] {facts.repo_id}",
            body=body,
            source=QASource(
                type="facts_field", repo_id=facts.repo_id,
                label=f"{facts.repo_id} · 全部子系统清单",
                anchor="kernel_features",
            ),
            tokens_est=_est_tokens(body),
        ))

    # 4) syscall（按需）
    if _need_any(req.question, _NEEDS_SYSCALL_TABLE):
        body = _fmt_syscalls_block(facts)
        items.append(QAContextItem(
            title=f"[syscall 表] {facts.repo_id}",
            body=body,
            source=QASource(
                type="facts_field", repo_id=facts.repo_id,
                label=f"{facts.repo_id} · syscall 表",
                detail=f"共 {facts.syscalls.count} 个",
                anchor="syscalls",
            ),
            tokens_est=_est_tokens(body),
        ))

    # 5) 开发历史（按需）
    if _need_any(req.question, _NEEDS_DEV_HISTORY):
        body = _fmt_dev_history_block(facts)
        items.append(QAContextItem(
            title=f"[开发历史] {facts.repo_id}",
            body=body,
            source=QASource(
                type="dev_history", repo_id=facts.repo_id,
                label=f"{facts.repo_id} · 开发历史",
                anchor="dev_history",
            ),
            tokens_est=_est_tokens(body),
        ))

    # 6) 目录（按需）
    if _need_any(req.question, _NEEDS_DIRECTORY):
        body = _fmt_directory_block(facts)
        items.append(QAContextItem(
            title=f"[目录结构] {facts.repo_id}",
            body=body,
            source=QASource(
                type="facts_field", repo_id=facts.repo_id,
                label=f"{facts.repo_id} · 目录结构",
                anchor="directory_tree",
            ),
            tokens_est=_est_tokens(body),
        ))

    # 受限：max_context_items
    if len(items) > req.max_context_items:
        items = items[: req.max_context_items]
        warns.append(f"上下文条目超过 {req.max_context_items}，已截断。")

    return items, warns


# ---------- compare ----------

def _load_compare_report(a: str, b: str) -> CompareReport | None:
    """优先复用磁盘上的 compare.json；如果没有就现算（保持本模块与 report 解耦）。"""
    if has_compare_json(a, b):
        try:
            data = json.loads(compare_json_path(a, b).read_text(encoding="utf-8"))
            return CompareReport.model_validate(data)
        except Exception:
            return None
    return None


def _retrieve_compare(req: QARequest) -> tuple[list[QAContextItem], list[str]]:
    warns: list[str] = []
    if not (req.repo_id_a and req.repo_id_b):
        return [], ["scope=compare 必须同时提供 repo_id_a 和 repo_id_b"]
    if req.repo_id_a == req.repo_id_b:
        return [], ["repo_id_a 与 repo_id_b 不能相同"]

    rpt = _load_compare_report(req.repo_id_a, req.repo_id_b)
    if rpt is None:
        # 反向查一次（compare 路径可能命名固定为 a<b）
        rpt = _load_compare_report(req.repo_id_b, req.repo_id_a)
    if rpt is None:
        return [], [
            f"对比报告不存在: ({req.repo_id_a}, {req.repo_id_b})，"
            "请先 POST /api/compare?a=...&b=... 生成。"
        ]

    items: list[QAContextItem] = []

    # 1) 评分卡
    sc = rpt.scores
    body = (
        f"- overall: {sc.overall:.3f}\n"
        f"- language: {sc.language:.3f}    architecture: {sc.architecture:.3f}\n"
        f"- build:    {sc.build:.3f}    base_template: {sc.base_template:.3f}\n"
        f"- subsystem_coverage: {sc.subsystem_coverage:.3f}    subsystem_avg: {sc.subsystem_avg:.3f}\n"
        f"- syscall:  {sc.syscall:.3f}    scale: {sc.scale:.3f}"
    )
    items.append(QAContextItem(
        title=f"[相似度评分] {rpt.a.repo_id} vs {rpt.b.repo_id}",
        body=body,
        source=QASource(
            type="compare_field", label="评分卡 (CompareScores)", anchor="scores",
        ),
        tokens_est=_est_tokens(body),
    ))

    # 2) 基本面 diff
    bd = rpt.basics
    body = (
        f"- A 主语言: {bd.language_main_a}    B 主语言: {bd.language_main_b}\n"
        f"- A 架构: {bd.arch_a}    B 架构: {bd.arch_b}\n"
        f"- A 构建: {bd.build_a}    B 构建: {bd.build_b}\n"
        f"- A 基线: {bd.base_template_a or '未识别'}    B 基线: {bd.base_template_b or '未识别'}"
        f"    基线相同: {bd.base_template_same}\n"
        f"- A LOC: {bd.total_loc_a}    B LOC: {bd.total_loc_b}    规模接近度: {bd.loc_ratio:.3f}"
    )
    items.append(QAContextItem(
        title="[基本面 diff]",
        body=body,
        source=QASource(
            type="compare_field", label="基本面对比 (BasicsDiff)", anchor="basics",
        ),
        tokens_est=_est_tokens(body),
    ))

    # 3) 亮点 / 差异
    hl = "\n".join(f"  * {x}" for x in rpt.highlights[:6]) or "  （无）"
    df = "\n".join(f"  * {x}" for x in rpt.differences[:6]) or "  （无）"
    body = f"亮点:\n{hl}\n\n差异:\n{df}"
    items.append(QAContextItem(
        title="[亮点 / 差异 摘要]",
        body=body,
        source=QASource(
            type="compare_field", label="亮点 / 差异", anchor="highlights",
        ),
        tokens_est=_est_tokens(body),
    ))

    # 4) 按问题命中子系统 diff（最多 3 个）
    feature_hits = _hit_features(req.question)
    sub_by_feat = {sd.feature: sd for sd in rpt.subsystems}
    if feature_hits:
        for feat in feature_hits:
            sd = sub_by_feat.get(feat)
            if not sd:
                continue
            kf_a = ", ".join(sd.key_functions_diff.common[:6]) or "（无共有）"
            ds_diff_a = ", ".join(sd.data_structures_diff.a_only[:6]) or "—"
            ds_diff_b = ", ".join(sd.data_structures_diff.b_only[:6]) or "—"
            body = (
                f"- 存在性: A={sd.present_a} B={sd.present_b}\n"
                f"- 文件数: A={sd.file_count_a} B={sd.file_count_b}\n"
                f"- 子系统相似度: {sd.similarity:.3f}\n"
                f"- 关键函数 共有: {kf_a}\n"
                f"- 数据结构 仅A: {ds_diff_a}\n"
                f"- 数据结构 仅B: {ds_diff_b}\n"
                f"- 备注: {sd.note}"
            )
            items.append(QAContextItem(
                title=f"[子系统 diff: {feat}]",
                body=body,
                source=QASource(
                    type="compare_field", label=f"子系统 diff · {feat}",
                    anchor=f"subsystems.{feat}",
                ),
                tokens_est=_est_tokens(body),
            ))
    else:
        # 默认给一个 top-3 相似度最高的子系统
        top = sorted(rpt.subsystems, key=lambda x: -x.similarity)[:3]
        for sd in top:
            body = (
                f"- 存在性: A={sd.present_a} B={sd.present_b}\n"
                f"- 相似度: {sd.similarity:.3f}\n"
                f"- 备注: {sd.note}"
            )
            items.append(QAContextItem(
                title=f"[子系统 diff: {sd.feature}]",
                body=body,
                source=QASource(
                    type="compare_field", label=f"子系统 diff · {sd.feature}",
                    anchor=f"subsystems.{sd.feature}",
                ),
                tokens_est=_est_tokens(body),
            ))

    # 5) syscall diff（按需 或 问题不限）
    sy = rpt.syscalls
    body = (
        f"- A syscall 数: {sy.count_a}    B: {sy.count_b}\n"
        f"- A 分类: {dict(sy.by_category_a)}\n"
        f"- B 分类: {dict(sy.by_category_b)}\n"
        f"- 名集合 Jaccard: {sy.names_diff.jaccard:.3f}\n"
        f"- 共有名（前 12）: {', '.join(sy.names_diff.common[:12]) or '（无）'}\n"
        f"- 仅 A: {', '.join(sy.names_diff.a_only[:8]) or '—'}\n"
        f"- 仅 B: {', '.join(sy.names_diff.b_only[:8]) or '—'}"
    )
    items.append(QAContextItem(
        title="[syscall diff]",
        body=body,
        source=QASource(
            type="compare_field", label="syscall diff", anchor="syscalls",
        ),
        tokens_est=_est_tokens(body),
    ))

    if len(items) > req.max_context_items:
        items = items[: req.max_context_items]
        warns.append(f"上下文条目超过 {req.max_context_items}，已截断。")

    return items, warns
