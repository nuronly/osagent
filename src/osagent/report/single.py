"""单仓库分析报告（Markdown）。

章节顺序对齐参考站点 d5206 的报告结构，并在每个段落里做更精准的内容：
1. 项目概述
2. 仓库目录结构
3. 核心系统组件分析（按 8 大子系统）
4. 系统调用清单（按分类）
5. 技术特点
6. 项目总结
7. 元信息

输入：RepoFacts + RepoEntry（提供学校/年份/比赛等元信息）
输出：Markdown 字符串
"""
from __future__ import annotations

from datetime import datetime

from ..schemas import KernelFeature, RepoEntry, RepoFacts, SyscallTable
from ..analyzer.directory_tree import render_ascii
from ..analyzer.syscall_dict import CATEGORY_LABEL_ZH, CATEGORY_ORDER

# 子系统的中文名 + 报告中出现的次序
_FEATURE_ORDER: list[tuple[str, str]] = [
    ("boot",       "引导与初始化系统"),
    ("memory",     "内存管理系统"),
    ("process",    "进程与线程管理系统"),
    ("scheduler",  "任务调度系统"),
    ("syscall",    "异常与系统调用系统"),
    ("trap",       "陷入与中断系统"),
    ("filesystem", "文件系统"),
    ("driver",     "设备驱动"),
    ("virtio",     "VirtIO 子系统"),
    ("ipc",        "进程间通信与同步"),
    ("signal",     "信号机制"),
    ("smp",        "多核支持"),
    ("network",    "网络协议栈"),
]


# ---------------- 顶层 ----------------

def render_markdown(facts: RepoFacts, *, entry: RepoEntry | None = None) -> str:
    """主入口：生成完整的 Markdown 报告。"""
    parts: list[str] = []

    parts.append(_render_header(facts, entry))
    parts.append(_render_overview(facts, entry))
    parts.append(_render_directory_tree(facts))
    parts.append(_render_subsystems(facts))
    parts.append(_render_syscalls(facts.syscalls))
    parts.append(_render_tech_highlights(facts))
    parts.append(_render_summary(facts))
    parts.append(_render_meta(facts))

    return "\n\n".join(p for p in parts if p)


# ---------------- 头 / 概览 ----------------

def _render_header(facts: RepoFacts, entry: RepoEntry | None) -> str:
    name = entry.team if entry else facts.repo_id
    return f"# {name} · 分析报告"


def _render_overview(facts: RepoFacts, entry: RepoEntry | None) -> str:
    b = facts.basics
    lang_main = b.languages[0].language if b.languages else "未识别"
    lang_all = "、".join(s.language for s in b.languages[:6]) or "未识别"
    arch = "、".join(b.arch) or "未识别"

    rows = [
        ("项目名称",   entry.team if entry else facts.repo_id),
        ("仓库 ID",    facts.repo_id),
    ]
    if entry is not None:
        rows.extend([
            ("仓库地址",   entry.repo_url),
            ("年份",       str(entry.year)),
            ("比赛名称",   entry.contest),
            ("赛道",       entry.track),
            ("参赛学校",   entry.school),
        ])
    rows.extend([
        ("开发语言",       f"{lang_main}（主），其他：{lang_all}"),
        ("目标架构",       arch),
        ("构建系统",       b.build.kind),
        ("总代码行数",     f"{b.total_loc:,}"),
        ("识别基线模板",   b.base_template or "未识别（疑似独立实现）"),
    ])

    md = ["## 项目概述", "", "| 字段 | 取值 |", "| --- | --- |"]
    for k, v in rows:
        md.append(f"| {k} | {_escape_md_cell(str(v))} |")
    return "\n".join(md)


# ---------------- 目录结构 ----------------

def _render_directory_tree(facts: RepoFacts) -> str:
    if facts.directory_tree is None:
        return ""
    tree_text = render_ascii(facts.directory_tree)
    return "## 仓库目录结构\n\n```text\n" + tree_text + "\n```"


# ---------------- 子系统 ----------------

def _render_subsystems(facts: RepoFacts) -> str:
    by_feat = {f.feature: f for f in facts.kernel_features}
    md: list[str] = ["## 核心系统组件分析"]
    idx = 0
    for key, label in _FEATURE_ORDER:
        kf = by_feat.get(key)
        if kf is None:
            continue
        idx += 1
        md.append(f"\n### {idx}. {label}")
        md.append(_render_one_subsystem(kf))
    return "\n".join(md) if idx > 0 else ""


def _render_one_subsystem(kf: KernelFeature) -> str:
    out: list[str] = []
    if kf.description:
        out.append(kf.description)
    if kf.implementation:
        out.append(f"**实现概要**：{kf.implementation}")
    if kf.feature_tags:
        out.append("**功能特征**：" + "、".join(f"`{t}`" for t in kf.feature_tags))

    if kf.files:
        out.append("\n**主要文件**：")
        for f in kf.files[:8]:
            out.append(f"- `{f}`")

    if kf.key_functions:
        out.append("\n**关键函数**：" + "、".join(f"`{n}`" for n in kf.key_functions))

    if kf.data_structures:
        out.append("\n**关键数据结构**：" + "、".join(f"`{n}`" for n in kf.data_structures))

    if kf.code_excerpts:
        out.append("\n**代码示例**：")
        for ex in kf.code_excerpts:
            cap = ex.caption or f"`{ex.file}:{ex.start_line}-{ex.end_line}`"
            out.append(f"\n_{cap}（{ex.file}:{ex.start_line}-{ex.end_line}）_")
            lang = ex.lang or ""
            out.append(f"```{lang}\n{ex.code}\n```")

    if kf.llm_summary:
        out.append(f"\n> 💡 {kf.llm_summary}")

    return "\n".join(out)


# ---------------- syscall ----------------

def _render_syscalls(table: SyscallTable) -> str:
    if table.count == 0:
        return ""
    md: list[str] = [f"## 系统调用清单（共 {table.count} 个）"]
    if table.dispatcher_file:
        md.append(f"\n**调度器位置**：`{table.dispatcher_file}`")

    # 按分类分组
    by_cat: dict[str, list] = {c: [] for c in CATEGORY_ORDER}
    for s in table.items:
        by_cat.setdefault(s.category, []).append(s)

    for cat in CATEGORY_ORDER:
        items = by_cat.get(cat) or []
        if not items:
            continue
        label = CATEGORY_LABEL_ZH.get(cat, cat)
        md.append(f"\n### {label}（{len(items)}）")
        for s in items:
            desc = s.description or "（未在内置字典中找到一句话描述）"
            md.append(f"- `{s.name}` — {desc}")
    return "\n".join(md)


# ---------------- 技术特点 ----------------

def _render_tech_highlights(facts: RepoFacts) -> str:
    if not facts.tech_highlights:
        return ""
    md: list[str] = ["## 技术特点"]
    for i, h in enumerate(facts.tech_highlights, 1):
        md.append(f"\n### {i}. {h.title}")
        md.append(h.summary)
        for b in h.bullets:
            md.append(f"- {b}")
    return "\n".join(md)


# ---------------- 项目总结 ----------------

def _render_summary(facts: RepoFacts) -> str:
    if not facts.project_summary:
        return ""
    md = ["## 项目总结"]
    for i, line in enumerate(facts.project_summary, 1):
        md.append(f"{i}. {line}")
    return "\n".join(md)


# ---------------- 元信息 ----------------

def _render_meta(facts: RepoFacts) -> str:
    return (
        "## 元信息\n\n"
        f"- **分析工具**：osAgent v{facts.schema_version}（L1+L2 静态分析）\n"
        f"- **分析时间**：{facts.extracted_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"- **HEAD commit**：`{facts.head_commit or '未记录'}`\n"
        f"- **事实表 schema**：v{facts.schema_version}\n"
    )


# ---------------- 工具 ----------------

def _escape_md_cell(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")
