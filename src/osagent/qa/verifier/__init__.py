"""QA 抗幻觉 verifier（Pro 版单模型实现）。

流程：
1. CitationCop（规则）形式审查：编号是否在 sources 范围内、文件/行号是否存在；
2. ClaimSplitter（LLM 第 1 跳）把 answer 拆成 atomic claims；
3. ClaimVerifier（LLM 第 2 跳）拿每条 claim + 证据，逐条判 supported/partial/unsupported；
4. Arbiter（纯规则）汇总给出 Verdict。

设计要点：
- claim 粒度拆分 → 避免"整段笼统判可信"的偷懒；
- verifier 上下文不含原 query → 避免被原意图带偏；
- temperature=0 + JSON 强约束；
- 任一步失败都不阻塞主流程（status=skipped）。
"""
from ...schemas.verification import (
    CitationCheck,
    ClaimVerdict,
    VerificationReport,
    VerificationStatus,
    VerifiedClaim,
)
from .committee import verify

__all__ = [
    "verify",
    "CitationCheck",
    "ClaimVerdict",
    "VerificationReport",
    "VerificationStatus",
    "VerifiedClaim",
]
