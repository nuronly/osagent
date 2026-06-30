"""Verifier 总编排。

公开入口：``verify(answer, items, sources)`` → VerificationReport

流程：
1. citation_cop 形式审查（纯规则，无成本）
2. 若 1 失败 → 直接 rejected（语义审查也救不回来）
3. split_claims 拆 claim
4. verify_claims 逐条核验
5. arbiter 综合给出 status
"""
from __future__ import annotations

import time

from ...logging import logger
from ...schemas.qa import QAContextItem, QASource
from ...schemas.verification import VerificationReport, VerificationStatus, VerifiedClaim
from . import citation_cop, claim_verifier


def _arbitrate(
    citation_pass: bool,
    claims: list[VerifiedClaim],
) -> tuple[VerificationStatus, str]:
    """根据规则给出最终 status + 一句话摘要。"""
    if not citation_pass:
        return "rejected", "❌ 引用形式审查不通过（编号超界 / 文件名不匹配 / 行号越界）"

    if not claims:
        return "skipped", "⚪ verifier 未拆出 claim（可能答复无实质内容）"

    n_sup = sum(1 for c in claims if c.verdict == "supported")
    n_par = sum(1 for c in claims if c.verdict == "partial")
    n_uns = sum(1 for c in claims if c.verdict == "unsupported")
    n_unv = sum(1 for c in claims if c.verdict == "unverifiable")
    total = len(claims)

    if n_uns > 0:
        return "rejected", f"❌ 发现 {n_uns}/{total} 处证据不支持的事实点，建议拒收或人工复核"
    if n_par > 0 or n_unv > 0:
        return (
            "partial",
            f"⚠️ {n_sup}/{total} 条证据完整支持，{n_par} 处部分支持 / {n_unv} 处无法核实",
        )
    return "verified", f"✅ {total}/{total} 条事实点均由证据完整支持"


def verify(
    answer: str,
    items: list[QAContextItem],
    sources: list[QASource],
    *,
    enabled: bool = True,
) -> VerificationReport:
    """主入口。任何异常都不抛，降级为 status=skipped。"""
    t0 = time.time()
    report = VerificationReport(status="skipped")

    if not enabled:
        report.summary = "verifier 已关闭"
        return report

    if not answer.strip():
        report.summary = "答复为空，跳过核验"
        return report

    # 步骤 1: 形式审查
    try:
        report.citation_checks = citation_cop.check(answer, sources)
    except Exception as e:
        logger.exception("citation_cop 失败")
        report.warnings.append(f"citation_cop failed: {type(e).__name__}: {e}")
        report.summary = "形式审查异常，已跳过"
        report.verifier_latency_ms = int((time.time() - t0) * 1000)
        return report

    citation_pass = citation_cop.all_passed(report.citation_checks)

    # 形式审查失败：直接 reject，不再调 LLM 浪费成本
    if not citation_pass:
        report.status = "rejected"
        report.summary = "❌ 引用形式审查不通过（编号超界 / 文件名不匹配 / 行号越界）"
        report.verifier_latency_ms = int((time.time() - t0) * 1000)
        return report

    # 步骤 2: LLM 语义审查
    claims: list[VerifiedClaim] = []
    verifier_model = ""
    try:
        raw_claims, m1, _u1 = claim_verifier.split_claims(answer)
        verifier_model = m1
        if raw_claims:
            claims, m2, _u2 = claim_verifier.verify_claims(raw_claims, items)
            verifier_model = m2 or m1
    except Exception as e:
        logger.exception("LLM verifier 失败")
        report.warnings.append(f"llm verifier failed: {type(e).__name__}: {e}")
        report.status = "skipped"
        report.summary = "⚪ 语义核验异常，已跳过（仅形式审查通过）"
        report.verifier_latency_ms = int((time.time() - t0) * 1000)
        return report

    report.claims = claims
    report.verifier_model = verifier_model
    report.n_supported = sum(1 for c in claims if c.verdict == "supported")
    report.n_partial = sum(1 for c in claims if c.verdict == "partial")
    report.n_unsupported = sum(1 for c in claims if c.verdict == "unsupported")
    report.n_unverifiable = sum(1 for c in claims if c.verdict == "unverifiable")

    # 步骤 3: 仲裁
    status, summary = _arbitrate(citation_pass, claims)
    report.status = status
    report.summary = summary
    report.verifier_latency_ms = int((time.time() - t0) * 1000)
    return report
