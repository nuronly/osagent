"""两仓库对比报告（Markdown 渲染）。

章节：
1. 概览（仓库 A vs 仓库 B 元信息表）
2. 相似度评分（带 progress bar 风格的等宽块字符）
3. 关键亮点 / 关键差异
4. 基本面对比（语言/架构/构建/基线/规模）
5. 核心系统组件并排对比（每个共有子系统一节，文件/函数/结构/标签集合 diff）
6. 系统调用对比
7. 开发演进对比
8. 元信息

输入：CompareReport
输出：Markdown 字符串
"""
from __future__ import annotations

from datetime import datetime

from ..schemas.compare import (
    CompareReport,
    SetDiff,
    SubsystemDiff,
)
from ..analyzer.syscall_dict import CATEGORY_LABEL_ZH, CATEGORY_ORDER

# ---- 入口 ----

def render_markdown(report: CompareReport) -> str:
    parts: list[str] = []
    parts.append(_render_header(report))
    parts.append(_render_overview_table(report))
    parts.append(_render_scores(report))
    parts.append(_render_highlights_diffs(report))
    parts.append(_render_basics(report))
    parts.append(_render_subsystems(report))
    parts.append(_render_syscalls(report))
    parts.append(_render_dev(report))
    parts.append(_render_meta(report))
    return "\n\n".join(p for p in parts if p)


# ---- 头 ----

def _label(meta) -> str:
    return meta.team or meta.repo_id


def _render_header(r: CompareReport) -> str:
    return f"# 两仓库对比报告：{_label(r.a)} vs {_label(r.b)}"


# ---- 元信息表 ----

def _render_overview_table(r: CompareReport) -> str:
    md: list[str] = ["## 仓库概览", "", "| 字段 | A | B |", "| --- | --- | --- |"]
    rows = [
        ("项目名称", _label(r.a), _label(r.b)),
        ("仓库 ID",  f"`{r.a.repo_id}`", f"`{r.b.repo_id}`"),
        ("参赛学校", r.a.school or "—", r.b.school or "—"),
        ("年份",     str(r.a.year) if r.a.year else "—", str(r.b.year) if r.b.year else "—"),
        ("仓库地址", r.a.repo_url or "—", r.b.repo_url or "—"),
        ("HEAD",     f"`{(r.a.head_commit or '—')[:12]}`", f"`{(r.b.head_commit or '—')[:12]}`"),
    ]
    for k, va, vb in rows:
        md.append(f"| {k} | {_escape(va)} | {_escape(vb)} |")
    return "\n".join(md)


# ---- 相似度评分 ----

def _bar(v: float, width: int = 20) -> str:
    """用 █ / · 画一个 [0,1] 进度条；空字符避免破坏表格对齐。"""
    v = max(0.0, min(1.0, v))
    filled = int(round(v * width))
    return "█" * filled + "·" * (width - filled)


def _grade(v: float) -> str:
    if v >= 0.7: return "高"
    if v >= 0.4: return "中"
    return "低"


def _render_scores(r: CompareReport) -> str:
    s = r.scores
    rows = [
        ("整体相似度",            s.overall,              "0.10*lang+0.05*arch+0.05*build+0.10*base+0.15*cov+0.30*sub+0.20*syscall+0.05*scale"),
        ("子系统平均",            s.subsystem_avg,        "共有子系统的 similarity 均值"),
        ("子系统覆盖度",          s.subsystem_coverage,   "子系统集合 Jaccard"),
        ("系统调用",              s.syscall,              "syscall 名集合 Jaccard"),
        ("语言",                  s.language,             "语言集合 Jaccard"),
        ("架构",                  s.architecture,         "架构集合 Jaccard"),
        ("构建系统",              s.build,                "1 同 / 0 异"),
        ("基线模板",              s.base_template,        "1 同 / 0 异（含未识别）"),
        ("规模接近度",            s.scale,                "min(LOC)/max(LOC)"),
    ]
    md = [
        "## 相似度评分",
        "",
        "> **整体相似度** = 子系统占主、syscall 次之、基本面辅助加权综合。",
        "",
        "| 维度 | 分值 | 进度 | 评级 | 说明 |",
        "| --- | ---: | --- | :---: | --- |",
    ]
    for label, val, expl in rows:
        md.append(
            f"| {label} | {val:.2f} | `{_bar(val)}` | **{_grade(val)}** | {expl} |"
        )
    return "\n".join(md)


# ---- 关键亮点 / 差异 ----

def _render_highlights_diffs(r: CompareReport) -> str:
    md: list[str] = ["## 关键亮点与差异"]
    if r.highlights:
        md.append("\n### ✅ 共性亮点")
        for h in r.highlights:
            md.append(f"- {h}")
    if r.differences:
        md.append("\n### ⚠️ 显著差异")
        for d in r.differences:
            md.append(f"- {d}")
    if not r.highlights and not r.differences:
        md.append("\n_未识别出显著的共性或差异。_")
    return "\n".join(md)


# ---- 基本面 ----

def _render_basics(r: CompareReport) -> str:
    b = r.basics
    md = [
        "## 基本面对比",
        "",
        "| 字段 | A | B | 评价 |",
        "| --- | --- | --- | :---: |",
    ]
    md.append(
        f"| 主语言 | `{b.language_main_a or '—'}` | `{b.language_main_b or '—'}` | "
        f"{'✅ 同' if b.language_main_a == b.language_main_b and b.language_main_a else '⚠️ 异'} |"
    )
    md.append(
        f"| 全部语言 | {_join_code(b.language_set.common + b.language_set.a_only) or '—'} | "
        f"{_join_code(b.language_set.common + b.language_set.b_only) or '—'} | "
        f"Jaccard={b.language_set.jaccard:.2f} |"
    )
    md.append(
        f"| 目标架构 | {_join_code(b.arch_a) or '—'} | {_join_code(b.arch_b) or '—'} | "
        f"Jaccard={b.arch_set.jaccard:.2f} |"
    )
    md.append(
        f"| 构建系统 | `{b.build_a or '—'}` | `{b.build_b or '—'}` | "
        f"{'✅ 同' if b.build_a == b.build_b and b.build_a else '⚠️ 异'} |"
    )
    md.append(
        f"| 基线模板 | `{b.base_template_a or '未识别'}` | `{b.base_template_b or '未识别'}` | "
        f"{'✅ 同' if b.base_template_same else '⚠️ 异'} |"
    )
    md.append(
        f"| 总代码行 | {b.total_loc_a:,} | {b.total_loc_b:,} | "
        f"接近度 {b.loc_ratio:.2f} |"
    )
    return "\n".join(md)


# ---- 子系统并排 ----

def _render_subsystems(r: CompareReport) -> str:
    if not r.subsystems:
        return ""
    md: list[str] = ["## 核心系统组件并排对比"]

    # 先一张总表
    md.append("")
    md.append("| # | 子系统 | A | B | 相似度 | 说明 |")
    md.append("| ---: | --- | :---: | :---: | ---: | --- |")
    for i, s in enumerate(r.subsystems, 1):
        a_mark = f"✅ ({s.file_count_a})" if s.present_a else "—"
        b_mark = f"✅ ({s.file_count_b})" if s.present_b else "—"
        sim = f"{s.similarity:.2f}" if s.present_a and s.present_b else "—"
        md.append(f"| {i} | **{s.label_zh}** | {a_mark} | {b_mark} | {sim} | {_escape(s.note)} |")

    # 然后每个共有子系统的细节
    md.append("\n### 共有子系统的细节差异")
    common = [s for s in r.subsystems if s.present_a and s.present_b]
    if not common:
        md.append("\n_无共有子系统。_")
        return "\n".join(md)

    for i, s in enumerate(common, 1):
        md.append(f"\n#### {i}. {s.label_zh}（相似度 {s.similarity:.2f}）")
        md.append(_render_one_subsystem_detail(s))
    return "\n".join(md)


def _render_one_subsystem_detail(s: SubsystemDiff) -> str:
    md: list[str] = []
    md.append(
        f"- 文件命中：A {s.file_count_a} 个 / B {s.file_count_b} 个，"
        f"Jaccard={s.files_diff.jaccard:.2f}"
    )
    md.append(_set_lines("文件", s.files_diff, code=True))
    md.append(_set_lines("关键函数", s.key_functions_diff, code=True))
    md.append(_set_lines("数据结构", s.data_structures_diff, code=True))
    md.append(_set_lines("功能特征", s.feature_tags_diff, code=True))
    return "\n".join(line for line in md if line)


def _set_lines(label: str, d: SetDiff, *, code: bool = False, max_each: int = 12) -> str:
    """渲染一个集合 diff 的三段（仅 A / 共有 / 仅 B），超量截断。"""
    if not (d.a_only or d.b_only or d.common):
        return ""
    def _fmt(items: list[str]) -> str:
        items = list(items)
        if not items:
            return "—"
        shown = items[:max_each]
        more = f"… +{len(items) - max_each}" if len(items) > max_each else ""
        if code:
            return "、".join(f"`{x}`" for x in shown) + ((" " + more) if more else "")
        return "、".join(shown) + ((" " + more) if more else "")
    lines = [f"\n**{label}**"]
    lines.append(f"- 🟦 共有：{_fmt(d.common)}")
    if d.a_only:
        lines.append(f"- 🟥 仅 A：{_fmt(d.a_only)}")
    if d.b_only:
        lines.append(f"- 🟩 仅 B：{_fmt(d.b_only)}")
    return "\n".join(lines)


# ---- syscall ----

def _render_syscalls(r: CompareReport) -> str:
    s = r.syscalls
    if s.count_a == 0 and s.count_b == 0:
        return ""
    md: list[str] = ["## 系统调用对比"]

    md.append(
        f"\nA 共 **{s.count_a}** 个，B 共 **{s.count_b}** 个，"
        f"公共 {s.common_count} 个（Jaccard={s.names_diff.jaccard:.2f}）。"
    )

    # 分类对比表
    cats = list(CATEGORY_ORDER) + sorted(
        (set(s.by_category_a) | set(s.by_category_b)) - set(CATEGORY_ORDER)
    )
    md.append("\n### 分类分布")
    md.append("\n| 分类 | A | B |")
    md.append("| --- | ---: | ---: |")
    for c in cats:
        ca = s.by_category_a.get(c, 0)
        cb = s.by_category_b.get(c, 0)
        if ca == 0 and cb == 0:
            continue
        label = CATEGORY_LABEL_ZH.get(c, c)
        md.append(f"| {label} | {ca} | {cb} |")

    # 名字 diff
    md.append("\n### 名字集合差异")
    md.append(_set_lines("系统调用", s.names_diff, code=True, max_each=20))
    return "\n".join(md)


# ---- 开发演进 ----

def _render_dev(r: CompareReport) -> str:
    d = r.dev
    if d.commits_a == 0 and d.commits_b == 0:
        return ""
    md = [
        "## 开发演进对比",
        "",
        "| 维度 | A | B |",
        "| --- | ---: | ---: |",
        f"| 提交数 | {d.commits_a} | {d.commits_b} |",
        f"| 贡献者数 | {d.contributors_a} | {d.contributors_b} |",
        f"| 首次提交 | {d.first_a or '—'} | {d.first_b or '—'} |",
        f"| 最近提交 | {d.last_a or '—'} | {d.last_b or '—'} |",
    ]
    return "\n".join(md)


# ---- meta ----

def _render_meta(r: CompareReport) -> str:
    return (
        "## 元信息\n\n"
        f"- **对比时间**：{r.generated_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"- **报告 schema**：v{r.schema_version}\n"
        f"- **数据来源**：A、B 各自的事实表（osAgent L1+L2 静态分析）\n"
    )


# ---- 小工具 ----

def _escape(s: str) -> str:
    return s.replace("|", "\\|").replace("\n", " ")


def _join_code(items) -> str:
    return "、".join(f"`{x}`" for x in items if x)
