"""从 collected-data.xlsx 构建仓库清单 manifest.json。"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

import openpyxl

from ..config import settings
from ..logging import logger
from ..schemas import Manifest, RepoEntry, RepoStatus

# Excel 表头映射（与 collected-data.xlsx 对齐）
COL_YEAR = 0
COL_CONTEST = 1
COL_TRACK = 2
COL_SCHOOL = 3
COL_TEAM = 4
COL_URL = 5


# 保留中英文 / 数字 / 下划线 / 连字符；其他字符（空格、标点、emoji）替换为 -
_SLUG_PATTERN = re.compile(r"[^\w\-\u4e00-\u9fff]+", flags=re.UNICODE)


def _slug(text: str, max_len: int = 30) -> str:
    text = _SLUG_PATTERN.sub("-", text.strip()).strip("-")
    return text[:max_len] or "unknown"


def _detect_host(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return "other"
    if "eduxiji" in host:
        return "gitlab.eduxiji.net"
    if "github" in host:
        return "github.com"
    if "gitee" in host:
        return "gitee.com"
    return "other"


def _make_repo_id(year: int, idx: int, team: str) -> str:
    return f"{year}_{idx:03d}_{_slug(team)}"


def load_from_xlsx(xlsx_path: Path) -> list[RepoEntry]:
    """读取 Excel，返回原始 RepoEntry 列表（status = PENDING）。"""
    logger.info(f"读取数据集: {xlsx_path}")
    wb = openpyxl.load_workbook(xlsx_path, data_only=True, read_only=True)
    ws = wb[wb.sheetnames[0]]

    entries: list[RepoEntry] = []
    per_year_idx: Counter[int] = Counter()

    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i == 0:
            continue  # 表头
        if not row or row[COL_URL] is None:
            continue
        year = int(row[COL_YEAR])
        contest = str(row[COL_CONTEST] or "").strip()
        track = str(row[COL_TRACK] or "").strip()
        school = str(row[COL_SCHOOL] or "").strip()
        team = str(row[COL_TEAM] or "").strip()
        url = str(row[COL_URL]).strip()

        per_year_idx[year] += 1
        repo_id = _make_repo_id(year, per_year_idx[year], team)

        entries.append(
            RepoEntry(
                year=year,
                contest=contest,
                track=track,
                school=school,
                team=team,
                repo_url=url,
                repo_id=repo_id,
                host=_detect_host(url),  # type: ignore[arg-type]
                status=RepoStatus.PENDING,
            )
        )

    wb.close()
    logger.info(f"共解析 {len(entries)} 条仓库记录")
    return entries


def build_manifest(xlsx_path: Path | None = None, out_path: Path | None = None) -> Manifest:
    """构建并落盘 manifest.json。若已存在则保留 status / local_path 等运行时字段。"""
    settings.ensure_dirs()
    xlsx_path = xlsx_path or settings.dataset_xlsx
    out_path = out_path or settings.manifest_path

    new_entries = load_from_xlsx(xlsx_path)

    # 合并旧 manifest 的运行时状态
    if out_path.exists():
        try:
            old = Manifest.model_validate_json(out_path.read_text(encoding="utf-8"))
            old_map = {e.repo_id: e for e in old.repos}
            merged = 0
            for e in new_entries:
                if e.repo_id in old_map:
                    o = old_map[e.repo_id]
                    e.status = o.status
                    e.local_path = o.local_path
                    e.default_branch = o.default_branch
                    e.head_commit = o.head_commit
                    e.size_bytes = o.size_bytes
                    e.file_count = o.file_count
                    e.cloned_at = o.cloned_at
                    e.error_msg = o.error_msg
                    merged += 1
            logger.info(f"已从旧 manifest 合并 {merged} 条运行时状态")
        except Exception as exc:
            logger.warning(f"旧 manifest 解析失败，将覆盖: {exc}")

    manifest = Manifest(
        source_xlsx=str(xlsx_path),
        total=len(new_entries),
        repos=new_entries,
    )

    out_path.write_text(
        manifest.model_dump_json(indent=2, exclude_none=False),
        encoding="utf-8",
    )
    logger.info(f"manifest 已写入: {out_path}  (total={manifest.total})")
    return manifest


def load_manifest(path: Path | None = None) -> Manifest:
    path = path or settings.manifest_path
    if not path.exists():
        raise FileNotFoundError(f"manifest 不存在: {path}，请先 `osagent manifest build`")
    return Manifest.model_validate_json(path.read_text(encoding="utf-8"))


def save_manifest(manifest: Manifest, path: Path | None = None) -> None:
    path = path or settings.manifest_path
    path.write_text(manifest.model_dump_json(indent=2, exclude_none=False), encoding="utf-8")


def manifest_stats(manifest: Manifest) -> dict:
    by_year = Counter(e.year for e in manifest.repos)
    by_host = Counter(e.host for e in manifest.repos)
    by_status = Counter(e.status.value for e in manifest.repos)
    by_track = Counter(e.track for e in manifest.repos)
    schools = {e.school for e in manifest.repos}
    return {
        "total": manifest.total,
        "by_year": dict(sorted(by_year.items())),
        "by_host": dict(by_host),
        "by_status": dict(by_status),
        "by_track": dict(by_track),
        "schools_count": len(schools),
    }
