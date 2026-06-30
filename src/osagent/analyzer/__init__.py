"""静态分析（事实抽取层）。

架构（v2，2024-12 重构）：
- core.py        : 公共工具（walk_files / safe_read / SKIP_DIR / TimeBudget）
- l1_quick.py    : L1 QuickProfile（秒级：语言/架构/构建/模板/git）
- l2_kernel.py   : L2 KernelInsight（数十秒：子系统/syscall/函数节点）
- l3_signature.py: L3 StructuralSignature（按需：MinHash 签名）
- pipeline.py    : 编排 L1→L2→L3，输出 RepoFacts
- jobs.py        : 内存任务队列（submit/progress/result）
- storage.py     : 事实表落盘 (data/facts/<repo_id>.json)
- contract.py    : MCP Static Analyzer 接口契约
"""
from .contract import MCPToolSpec, RepoRef, StaticAnalyzer, list_mcp_tools
from .jobs import Job, JobManager, JobProgress, JobStatus, get_manager
from .pipeline import analyze, analyze_by_repo_id
from .storage import facts_path, has_facts, load_facts, save_facts

__all__ = [
    # 契约
    "StaticAnalyzer",
    "RepoRef",
    "MCPToolSpec",
    "list_mcp_tools",
    # 主入口
    "analyze",
    "analyze_by_repo_id",
    # 任务队列
    "get_manager",
    "JobManager",
    "Job",
    "JobProgress",
    "JobStatus",
    # 存储
    "save_facts",
    "load_facts",
    "has_facts",
    "facts_path",
]
