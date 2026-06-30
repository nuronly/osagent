"""报告生成。

- single.render_markdown(facts, entry) → Markdown 字符串
- html.render_html(md, title) → HTML 字符串
- build_report(repo_id) → 一站式：加载 facts + entry，输出 md/html 到 data/reports/
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from ..analyzer import load_facts, has_facts
from ..ingest import load_manifest
from .html import render_html
from .single import render_markdown
from .storage import has_html, has_md, html_path, md_path, save_html, save_md

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


__all__ = [
    "build_report",
    "render_markdown",
    "render_html",
    "md_path",
    "html_path",
    "has_md",
    "has_html",
    "save_md",
    "save_html",
]
