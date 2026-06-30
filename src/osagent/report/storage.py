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


# ---------- compare 报告 ----------

def compare_dir() -> Path:
    p = settings.data_dir / "reports" / "compare"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _compare_stem(a: str, b: str) -> str:
    """compare 文件名规则：a__vs__b（保持顺序敏感）。"""
    return f"{a}__vs__{b}"


def compare_md_path(a: str, b: str) -> Path:
    return compare_dir() / f"{_compare_stem(a, b)}.md"


def compare_html_path(a: str, b: str) -> Path:
    return compare_dir() / f"{_compare_stem(a, b)}.html"


def compare_json_path(a: str, b: str) -> Path:
    return compare_dir() / f"{_compare_stem(a, b)}.json"


def save_compare_md(a: str, b: str, text: str) -> Path:
    p = compare_md_path(a, b)
    p.write_text(text, encoding="utf-8")
    return p


def save_compare_html(a: str, b: str, text: str) -> Path:
    p = compare_html_path(a, b)
    p.write_text(text, encoding="utf-8")
    return p


def save_compare_json(a: str, b: str, text: str) -> Path:
    p = compare_json_path(a, b)
    p.write_text(text, encoding="utf-8")
    return p


def has_compare_md(a: str, b: str) -> bool:
    return compare_md_path(a, b).exists()


def has_compare_html(a: str, b: str) -> bool:
    return compare_html_path(a, b).exists()


def has_compare_json(a: str, b: str) -> bool:
    return compare_json_path(a, b).exists()
