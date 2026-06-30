"""事实表落盘：data/facts/<repo_id>.json。"""
from __future__ import annotations

import json
from pathlib import Path

from ..config import settings
from ..schemas import RepoFacts


def facts_dir() -> Path:
    return settings.facts_dir


def facts_path(repo_id: str) -> Path:
    return settings.facts_dir / f"{repo_id}.json"


def save_facts(facts: RepoFacts) -> Path:
    settings.ensure_dirs()
    p = facts_path(facts.repo_id)
    p.write_text(facts.model_dump_json(indent=2), encoding="utf-8")
    return p


def load_facts(repo_id: str) -> RepoFacts:
    p = facts_path(repo_id)
    if not p.exists():
        raise FileNotFoundError(f"事实表不存在: {p}，请先 `osagent analyze {repo_id}`")
    return RepoFacts.model_validate_json(p.read_text(encoding="utf-8"))


def has_facts(repo_id: str) -> bool:
    return facts_path(repo_id).exists()
