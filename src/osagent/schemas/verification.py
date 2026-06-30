"""Verifier 数据契约（放到 schemas/ 下避免循环 import）。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ClaimVerdict = Literal["supported", "partial", "unsupported", "unverifiable"]
"""逐条 claim 的判定：
- supported    证据完全支持
- partial      证据部分支持
- unsupported  证据明确不支持
- unverifiable 引用证据缺失，无法判定
"""

VerificationStatus = Literal[
    "verified",   # 全部 supported → 安全
    "partial",    # 有 partial 但无 unsupported → 灰色提示
    "rejected",   # 出现 unsupported / 形式审查失败 → 强烈建议拒收
    "skipped",    # verifier 自身失败 / 关闭 → 不阻塞主流程
]


class CitationCheck(BaseModel):
    """规则审查的逐编号结果。"""

    index: int
    ok: bool
    reason: str = ""


class VerifiedClaim(BaseModel):
    """拆出来并核验过的一条 atomic claim。"""

    claim: str
    cited_indices: list[int] = Field(default_factory=list)
    verdict: ClaimVerdict
    reason: str = ""
    evidence_quote: str = ""


class VerificationReport(BaseModel):
    """挂在 QAResponse.verification 上的整体核验结论。"""

    status: VerificationStatus
    summary: str = ""

    citation_checks: list[CitationCheck] = Field(default_factory=list)
    claims: list[VerifiedClaim] = Field(default_factory=list)

    n_supported: int = 0
    n_partial: int = 0
    n_unsupported: int = 0
    n_unverifiable: int = 0

    verifier_model: str = ""
    verifier_latency_ms: int = 0
    warnings: list[str] = Field(default_factory=list)
