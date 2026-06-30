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
