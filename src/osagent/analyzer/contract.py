"""MCP Static Analyzer 接口契约（Tool Schema）。

Static Analyzer 是抗幻觉的基石：它对外提供一组「确定性」工具，由 Agent
按需调用，把代码事实喂给 LLM。LLM 不允许越过事实表写结论。

本文件只定义工具的入参 / 出参契约（接口先行），具体实现在 W3–W4。
所有工具最终也会以 MCP Server 形式暴露，便于 Claude Code / Cursor 复用。

================== 工具列表（v1） ==================

1) repo.scan_basics                -> Basics
2) repo.detect_build_system        -> BuildSystem
3) repo.detect_arch                -> list[arch]
4) repo.detect_base_template       -> { template, evidence }
5) code.list_functions             -> list[FunctionNode]
6) code.build_call_graph           -> CallGraph
7) code.minhash_signature          -> list[int]
8) kernel.detect_subsystems        -> list[KernelFeature]
9) kernel.extract_syscalls         -> SyscallTable
10) git.dev_history                -> DevHistory
11) repo.full_facts                -> RepoFacts  (聚合 1–10)
"""
from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, Field

from ..schemas import (
    Basics,
    BuildSystem,
    CallGraph,
    DevHistory,
    Evidence,
    FunctionNode,
    KernelFeature,
    RepoFacts,
    SyscallTable,
)


# ============ 通用入参 ============

class RepoRef(BaseModel):
    """所有工具的统一入参：指定要分析哪个仓库。"""
    repo_id: str
    local_path: str
    head_commit: str | None = None


# ============ 工具：基础信息 ============

class DetectBaseTemplateOut(BaseModel):
    template: Literal[
        "rCore-Tutorial-v3", "rCore", "xv6-k210", "xv6-riscv",
        "uCore", "uCore-SMP", "blog_os", "custom", "unknown",
    ]
    confidence: Literal["high", "medium", "low"]
    evidence: list[Evidence]
    notes: str = ""


# ============ Protocol（接口契约） ============

class StaticAnalyzer(Protocol):
    """静态分析器的能力契约。所有实现（本地 Python 模块、MCP Server 等）
    都必须实现这些方法。"""

    # --- 基础 ---
    def scan_basics(self, ref: RepoRef) -> Basics: ...
    def detect_build_system(self, ref: RepoRef) -> BuildSystem: ...
    def detect_arch(self, ref: RepoRef) -> list[str]: ...
    def detect_base_template(self, ref: RepoRef) -> DetectBaseTemplateOut: ...

    # --- 代码结构 ---
    def list_functions(self, ref: RepoRef) -> list[FunctionNode]: ...
    def build_call_graph(self, ref: RepoRef) -> CallGraph: ...
    def minhash_signature(self, ref: RepoRef, num_perm: int = 128) -> list[int]: ...

    # --- 内核语义 ---
    def detect_subsystems(self, ref: RepoRef) -> list[KernelFeature]: ...
    def extract_syscalls(self, ref: RepoRef) -> SyscallTable: ...

    # --- Git ---
    def dev_history(self, ref: RepoRef) -> DevHistory: ...

    # --- 聚合 ---
    def full_facts(self, ref: RepoRef) -> RepoFacts: ...


# ============ MCP Tool 描述（供 MCP Server 注册时使用） ============

class MCPToolSpec(BaseModel):
    """单个 MCP 工具的元数据描述。"""
    name: str
    description: str
    input_schema: dict
    output_schema: dict


def list_mcp_tools() -> list[MCPToolSpec]:
    """返回本静态分析器对外暴露的所有 MCP 工具规格。

    实际 MCP Server 启动时调用此函数注册工具（W3 实现）。
    """
    return [
        MCPToolSpec(
            name="repo.scan_basics",
            description="扫描仓库基本面：语言占比 / loc / 架构 / 构建系统 / 基线模板",
            input_schema=RepoRef.model_json_schema(),
            output_schema=Basics.model_json_schema(),
        ),
        MCPToolSpec(
            name="repo.detect_build_system",
            description="识别构建系统（cargo/make/cmake/...）",
            input_schema=RepoRef.model_json_schema(),
            output_schema=BuildSystem.model_json_schema(),
        ),
        MCPToolSpec(
            name="repo.detect_base_template",
            description="识别仓库是否基于 rCore / xv6 / uCore 等基线模板",
            input_schema=RepoRef.model_json_schema(),
            output_schema=DetectBaseTemplateOut.model_json_schema(),
        ),
        MCPToolSpec(
            name="code.build_call_graph",
            description="构建函数调用图（tree-sitter + rust-analyzer/clangd）",
            input_schema=RepoRef.model_json_schema(),
            output_schema=CallGraph.model_json_schema(),
        ),
        MCPToolSpec(
            name="code.minhash_signature",
            description="基于调用图的 MinHash 签名，用于跨仓库结构同源检测",
            input_schema=RepoRef.model_json_schema(),
            output_schema={"type": "array", "items": {"type": "integer"}},
        ),
        MCPToolSpec(
            name="kernel.detect_subsystems",
            description="识别内核子系统（调度/内存/文件系统/...）并定位证据",
            input_schema=RepoRef.model_json_schema(),
            output_schema={"type": "array", "items": KernelFeature.model_json_schema()},
        ),
        MCPToolSpec(
            name="kernel.extract_syscalls",
            description="抽取 syscall 表与 dispatcher",
            input_schema=RepoRef.model_json_schema(),
            output_schema=SyscallTable.model_json_schema(),
        ),
        MCPToolSpec(
            name="git.dev_history",
            description="抽取 commit 时间线 / 贡献者 / 里程碑",
            input_schema=RepoRef.model_json_schema(),
            output_schema=DevHistory.model_json_schema(),
        ),
        MCPToolSpec(
            name="repo.full_facts",
            description="一次性聚合输出完整事实表（供 Agent 主流程调用）",
            input_schema=RepoRef.model_json_schema(),
            output_schema=RepoFacts.model_json_schema(),
        ),
    ]
