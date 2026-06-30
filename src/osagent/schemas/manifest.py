"""数据契约：仓库清单 manifest。

manifest.json 描述五届 168 个仓库的元数据 + 拉取状态，作为后续所有流程
（拉取、分析、检索、报告）的唯一数据入口（single source of truth）。
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class RepoStatus(str, Enum):
    PENDING = "pending"          # 尚未尝试
    OK = "ok"                    # 已成功克隆
    UNREACHABLE = "unreachable"  # 链接失效 / 仓库不存在 / 私有
    TIMEOUT = "timeout"
    ERROR = "error"


class RepoEntry(BaseModel):
    """一条仓库记录（与 Excel 一行对应）。"""

    # 来自 Excel 的原始字段
    year: int
    contest: str = Field(description="赛事，如 '操作系统赛'")
    track: str = Field(description="子赛事，如 '内核实现赛道'")
    school: str
    team: str
    repo_url: str

    # 派生字段
    repo_id: str = Field(description="稳定 ID，用于落盘目录名（year_序号_team-slug）")
    host: Literal["gitlab.eduxiji.net", "github.com", "gitee.com", "other"] = "other"

    # 拉取状态
    status: RepoStatus = RepoStatus.PENDING
    local_path: str | None = None
    default_branch: str | None = None
    head_commit: str | None = None
    size_bytes: int | None = None
    file_count: int | None = None
    cloned_at: datetime | None = None
    error_msg: str | None = None


class Manifest(BaseModel):
    """整个数据集的清单。"""

    version: str = "1.0"
    generated_at: datetime = Field(default_factory=datetime.now)
    source_xlsx: str
    total: int
    repos: list[RepoEntry]


# ------------ Manifest 增量导入 / 单仓添加 / 删除（v0.7） ------------

class ManualRepoInput(BaseModel):
    """前端 / CLI 手工添加一条仓库时的输入。"""

    year: int
    team: str
    school: str
    repo_url: str
    contest: str = "操作系统赛"
    track: str = "内核实现赛道"


class ImportRowResult(BaseModel):
    """xlsx 增量导入时每行的结果。"""

    row: int = Field(description="Excel 中的行号（1-based，跳过表头）")
    action: Literal["added", "skipped", "error"]
    repo_id: str | None = None
    repo_url: str | None = None
    reason: str | None = None  # skipped / error 时填


class ImportReport(BaseModel):
    """xlsx 增量导入的总报告（同时用于 dry-run 预览与实际执行）。"""

    source: str = Field(description="xlsx 路径或上传文件名")
    mode: Literal["merge"] = "merge"
    dry_run: bool = False
    total_rows: int = 0
    added: int = 0
    skipped: int = 0
    errors: int = 0
    rows: list[ImportRowResult] = Field(default_factory=list)
    backup_path: str | None = Field(
        default=None,
        description="实际执行时（dry_run=False）写入的备份文件路径",
    )


class DeleteRepoResult(BaseModel):
    """删除一条仓库记录的结果。"""

    repo_id: str
    deleted: bool
    purged_paths: list[str] = Field(default_factory=list)
    skipped_paths: list[str] = Field(default_factory=list)
