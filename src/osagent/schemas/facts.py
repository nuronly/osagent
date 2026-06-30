"""数据契约：内核「事实表」（Facts）。

这是抗幻觉的核心：LLM 只允许在事实表上复述和解释，不允许凭空生成结论。

设计原则：
1. 所有字段必须可由静态分析直接得到（不依赖 LLM）；
2. 关键结论必须附带 evidence（文件 + 行号），可被独立 verifier 核验；
3. schema 稳定，后续 RAG / Project Card / Diff Report 直接消费。

注：本文件先定义接口骨架，具体抽取实现在 W3–W4。
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Confidence = Literal["high", "medium", "low"]


# ============ 通用 ============

class Evidence(BaseModel):
    """证据：文件路径 + 行号范围。每个 LLM 结论都必须挂一个。"""
    file: str
    start_line: int
    end_line: int


# ============ 基本面 ============

class LanguageStat(BaseModel):
    language: str         # Rust / C / Asm / Makefile ...
    loc: int
    percent: float


class BuildSystem(BaseModel):
    kind: Literal["cargo", "make", "cmake", "xmake", "meson", "unknown"]
    files: list[str]
    targets: list[str] = Field(default_factory=list)


class Basics(BaseModel):
    languages: list[LanguageStat]
    total_loc: int
    arch: list[Literal["riscv64", "riscv32", "x86_64", "aarch64", "loongarch64", "other"]]
    build: BuildSystem
    base_template: str | None = Field(
        default=None,
        description="识别出的基线模板（rCore-Tutorial-v3 / xv6-k210 / uCore 等），可为空",
    )
    base_template_evidence: list[Evidence] = Field(default_factory=list)


# ============ 内核子系统 ============

class KernelFeature(BaseModel):
    feature: Literal[
        "boot", "memory", "scheduler", "process", "syscall",
        "filesystem", "vfs", "driver", "ipc", "smp",
        "network", "signal", "trap", "virtio", "other",
    ]
    description: str = Field(description="一两句话，从源码事实总结，禁止主观评价")
    implementation: str = Field(description="具体实现方式（如 'CFS 红黑树'）")
    files: list[str]
    evidence: list[Evidence]
    confidence: Confidence


# ============ 系统调用 ============

class Syscall(BaseModel):
    number: int | None = None
    name: str
    handler_file: str | None = None
    handler_func: str | None = None
    evidence: Evidence | None = None


class SyscallTable(BaseModel):
    count: int
    items: list[Syscall]
    dispatcher_file: str | None = None


# ============ 调用图 ============

class FunctionNode(BaseModel):
    """函数节点（供 Call Graph MinHash 与 Project Card 使用）。"""
    qualified_name: str          # crate::mod::func 或 file.c:func
    file: str
    start_line: int
    end_line: int
    in_degree: int
    out_degree: int


class CallGraph(BaseModel):
    nodes: list[FunctionNode]
    edges_count: int
    minhash_signature: list[int] | None = Field(
        default=None, description="datasketch MinHash 签名，用于跨仓库结构同源检测"
    )


# ============ 开发历史 ============

class Commit(BaseModel):
    sha: str
    author_email: str
    timestamp: datetime
    message_first_line: str


class DevHistory(BaseModel):
    commits_total: int
    contributors_total: int
    first_commit_at: datetime | None = None
    last_commit_at: datetime | None = None
    milestones: list[Commit] = Field(
        default_factory=list,
        description="由 commit message 聚类生成的里程碑（W4 实现）",
    )


# ============ 顶层事实表 ============

class RepoFacts(BaseModel):
    """单个仓库的完整事实表，落盘为 data/facts/<repo_id>.json。"""

    schema_version: str = "1.0"
    repo_id: str
    extracted_at: datetime = Field(default_factory=datetime.now)
    head_commit: str

    basics: Basics
    kernel_features: list[KernelFeature]
    syscalls: SyscallTable
    call_graph: CallGraph
    dev_history: DevHistory

    # 给 RAG 用的"文本化摘要"，由结构化字段拼接而成（非 LLM 生成）
    summary_for_embedding: str = ""
