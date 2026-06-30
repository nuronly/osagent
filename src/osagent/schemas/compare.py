"""两仓库对比报告的数据契约。

设计原则与 RepoFacts 一致：
- 所有数值/集合都由 RepoFacts 静态推导，不依赖 LLM
- 每个 SubsystemDiff 都附带可追溯的文件/函数清单
- 相似度打分用确定性规则（Jaccard / 归一化差值），可解释

schema_version: 1.0
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# ---------------- 通用工具：单字段对比 ----------------

class ScalarDiff(BaseModel):
    """一个标量字段的对比。"""
    field: str
    a: str = ""
    b: str = ""
    same: bool = False


class SetDiff(BaseModel):
    """两个集合的并/交/差。"""
    a_only: list[str] = Field(default_factory=list)
    b_only: list[str] = Field(default_factory=list)
    common: list[str] = Field(default_factory=list)
    jaccard: float = 0.0  # |A∩B| / |A∪B|

    @property
    def union_size(self) -> int:
        return len(self.a_only) + len(self.b_only) + len(self.common)


# ---------------- 基本面 ----------------

class BasicsDiff(BaseModel):
    """基本信息层的对比：语言/架构/构建/基线/规模。"""
    language_main_a: str = ""
    language_main_b: str = ""
    language_set: SetDiff = Field(default_factory=SetDiff)

    arch_a: list[str] = Field(default_factory=list)
    arch_b: list[str] = Field(default_factory=list)
    arch_set: SetDiff = Field(default_factory=SetDiff)

    build_a: str = ""
    build_b: str = ""

    base_template_a: str = ""
    base_template_b: str = ""
    base_template_same: bool = False

    total_loc_a: int = 0
    total_loc_b: int = 0
    loc_ratio: float = 0.0  # min/max ∈ (0,1]，越接近 1 规模越接近


# ---------------- 子系统 ----------------

class SubsystemDiff(BaseModel):
    """单个内核子系统的两仓库对比。"""
    feature: str  # boot / memory / ...
    label_zh: str

    present_a: bool
    present_b: bool

    # 文件 / 关键函数 / 数据结构 / 特征标签 都做集合 diff
    files_diff: SetDiff = Field(default_factory=SetDiff)
    key_functions_diff: SetDiff = Field(default_factory=SetDiff)
    data_structures_diff: SetDiff = Field(default_factory=SetDiff)
    feature_tags_diff: SetDiff = Field(default_factory=SetDiff)

    # 文件数量
    file_count_a: int = 0
    file_count_b: int = 0

    # 子系统级相似度（多维加权综合）：0.0-1.0
    similarity: float = 0.0

    # 文字小结（确定性拼接，非 LLM）
    note: str = ""


# ---------------- syscall ----------------

class SyscallDiff(BaseModel):
    count_a: int = 0
    count_b: int = 0
    by_category_a: dict[str, int] = Field(default_factory=dict)
    by_category_b: dict[str, int] = Field(default_factory=dict)
    names_diff: SetDiff = Field(default_factory=SetDiff)
    # 公共 syscall 在两边的"分类是否一致"的简单统计
    common_count: int = 0


# ---------------- 演进 / 仓库元 ----------------

class DevDiff(BaseModel):
    commits_a: int = 0
    commits_b: int = 0
    contributors_a: int = 0
    contributors_b: int = 0
    first_a: str = ""
    first_b: str = ""
    last_a: str = ""
    last_b: str = ""


# ---------------- 顶层对比报告 ----------------

class RepoMeta(BaseModel):
    """对比时引用的仓库元信息（避免 compare 文件读两次 manifest）。"""
    repo_id: str
    team: str = ""
    school: str = ""
    year: int = 0
    repo_url: str = ""
    head_commit: str = ""


class CompareScores(BaseModel):
    """整体相似度子分数（0.0-1.0），最终一个 overall。"""
    language: float = 0.0
    architecture: float = 0.0
    build: float = 0.0
    base_template: float = 0.0
    subsystem_coverage: float = 0.0   # 子系统集合 Jaccard
    subsystem_avg: float = 0.0        # 共有子系统的平均 similarity
    syscall: float = 0.0              # syscall 名集合 Jaccard
    scale: float = 0.0                # LOC 接近度
    overall: float = 0.0              # 加权综合


class CompareReport(BaseModel):
    schema_version: str = "1.0"
    generated_at: datetime = Field(default_factory=datetime.now)

    a: RepoMeta
    b: RepoMeta

    basics: BasicsDiff = Field(default_factory=BasicsDiff)
    subsystems: list[SubsystemDiff] = Field(default_factory=list)
    syscalls: SyscallDiff = Field(default_factory=SyscallDiff)
    dev: DevDiff = Field(default_factory=DevDiff)

    scores: CompareScores = Field(default_factory=CompareScores)

    # 自动生成的"亮点 / 差异"摘要 bullets（确定性拼接）
    highlights: list[str] = Field(default_factory=list)
    differences: list[str] = Field(default_factory=list)
