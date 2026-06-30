"""报告生成。

- single.render_markdown(facts, entry) → Markdown 字符串
- html.render_html(md, title) → HTML 字符串
- build_report(repo_id) → 单仓库报告一站式
- build_compare_report(a, b) → 两仓库对比报告一站式
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from ..analyzer import load_facts, has_facts
from ..compare import compare_repos
from ..ingest import load_manifest
from .compare import render_markdown as render_compare_md
from .html import render_html
from .single import render_markdown
from .storage import (
    compare_html_path,
    compare_json_path,
    compare_md_path,
    has_compare_html,
    has_compare_json,
    has_compare_md,
    has_html,
    has_md,
    html_path,
    md_path,
    save_compare_html,
    save_compare_json,
    save_compare_md,
    save_html,
    save_md,
)

Format = Literal["md", "html", "both"]


def build_report(
    repo_id: str,
    *,
    fmt: Format = "both",
    save: bool = True,
) -> dict:
    """生成单仓库的分析报告。

    Returns:
        {"repo_id", "md_path"?, "html_path"?, "md_chars"?, "html_chars"?}
    """
    if not has_facts(repo_id):
        raise FileNotFoundError(
            f"事实表不存在: {repo_id}. 请先 osagent analyzer analyze {repo_id}"
        )

    facts = load_facts(repo_id)
    m = load_manifest()
    entry = next((r for r in m.repos if r.repo_id == repo_id), None)

    md_text = render_markdown(facts, entry=entry)

    out: dict = {"repo_id": repo_id, "md_chars": len(md_text)}

    if fmt in ("md", "both") and save:
        p = save_md(repo_id, md_text)
        out["md_path"] = str(p)

    if fmt in ("html", "both"):
        title = (entry.team if entry else repo_id) + " · 分析报告"
        html_text = render_html(md_text, title=title)
        out["html_chars"] = len(html_text)
        if save:
            p = save_html(repo_id, html_text)
            out["html_path"] = str(p)

    return out


def build_compare_report(
    repo_id_a: str,
    repo_id_b: str,
    *,
    fmt: Format = "both",
    save: bool = True,
    save_json_report: bool = True,
) -> dict:
    """生成两仓库对比报告（md + html）。

    Returns:
        {
          "a", "b",
          "overall", "subsystem_avg",
          "md_path"?, "html_path"?, "json_path"?,
          "md_chars"?, "html_chars"?
        }
    """
    report = compare_repos(repo_id_a, repo_id_b)
    md_text = render_compare_md(report)

    out: dict = {
        "a": repo_id_a,
        "b": repo_id_b,
        "overall": report.scores.overall,
        "subsystem_avg": report.scores.subsystem_avg,
        "md_chars": len(md_text),
    }

    if fmt in ("md", "both") and save:
        p = save_compare_md(repo_id_a, repo_id_b, md_text)
        out["md_path"] = str(p)

    if fmt in ("html", "both"):
        title = f"{(report.a.team or repo_id_a)} vs {(report.b.team or repo_id_b)} · 对比报告"
        html_text = render_html(md_text, title=title)
        out["html_chars"] = len(html_text)
        if save:
            p = save_compare_html(repo_id_a, repo_id_b, html_text)
            out["html_path"] = str(p)

    if save and save_json_report:
        p = save_compare_json(
            repo_id_a, repo_id_b,
            report.model_dump_json(indent=2),
        )
        out["json_path"] = str(p)

    return out


__all__ = [
    "build_report",
    "build_compare_report",
    "render_markdown",
    "render_compare_md",
    "render_html",
    "md_path",
    "html_path",
    "has_md",
    "has_html",
    "save_md",
    "save_html",
    "compare_md_path",
    "compare_html_path",
    "compare_json_path",
    "has_compare_md",
    "has_compare_html",
    "has_compare_json",
]
