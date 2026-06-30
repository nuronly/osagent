"""报告落盘：data/reports/<repo_id>.md / .html
"""
from __future__ import annotations

from pathlib import Path

from ..config import settings


def reports_dir() -> Path:
    p = settings.data_dir / "reports"
    p.mkdir(parents=True, exist_ok=True)
    return p


def md_path(repo_id: str) -> Path:
    return reports_dir() / f"{repo_id}.md"


def html_path(repo_id: str) -> Path:
    return reports_dir() / f"{repo_id}.html"


def save_md(repo_id: str, text: str) -> Path:
    p = md_path(repo_id)
    p.write_text(text, encoding="utf-8")
    return p


def save_html(repo_id: str, text: str) -> Path:
    p = html_path(repo_id)
    p.write_text(text, encoding="utf-8")
    return p


def has_md(repo_id: str) -> bool:
    return md_path(repo_id).exists()


def has_html(repo_id: str) -> bool:
    return html_path(repo_id).exists()
