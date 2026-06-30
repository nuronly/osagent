"""数据契约。"""
from .facts import (
    Basics,
    BuildSystem,
    CallGraph,
    CodeExcerpt,
    Commit,
    Confidence,
    DevHistory,
    DirectoryNode,
    Evidence,
    FunctionNode,
    KernelFeature,
    LanguageStat,
    RepoFacts,
    Syscall,
    SyscallTable,
    TechHighlight,
)
from .manifest import Manifest, RepoEntry, RepoStatus
from .compare import (
    BasicsDiff,
    CompareReport,
    CompareScores,
    DevDiff,
    RepoMeta,
    ScalarDiff,
    SetDiff,
    SubsystemDiff,
    SyscallDiff,
)
from .qa import (
    QAContextItem,
    QARequest,
    QAResponse,
    QAScope,
    QASource,
    QASourceType,
    TokenUsage,
)

__all__ = [
    "Manifest",
    "RepoEntry",
    "RepoStatus",
    "RepoFacts",
    "Basics",
    "BuildSystem",
    "CallGraph",
    "CodeExcerpt",
    "Commit",
    "Confidence",
    "DevHistory",
    "DirectoryNode",
    "Evidence",
    "FunctionNode",
    "KernelFeature",
    "LanguageStat",
    "Syscall",
    "SyscallTable",
    "TechHighlight",
    # compare
    "BasicsDiff",
    "CompareReport",
    "CompareScores",
    "DevDiff",
    "RepoMeta",
    "ScalarDiff",
    "SetDiff",
    "SubsystemDiff",
    "SyscallDiff",
    # qa
    "QAContextItem",
    "QARequest",
    "QAResponse",
    "QAScope",
    "QASource",
    "QASourceType",
    "TokenUsage",
]

# verification（抗幻觉核验报告）
from .verification import (  # noqa: E402
    CitationCheck,
    ClaimVerdict,
    VerificationReport,
    VerificationStatus,
    VerifiedClaim,
)

__all__ += [
    "CitationCheck",
    "ClaimVerdict",
    "VerificationReport",
    "VerificationStatus",
    "VerifiedClaim",
]
