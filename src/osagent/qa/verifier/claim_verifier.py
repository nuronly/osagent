"""LLM 核验员。

两跳 prompt：
1. ``split_claims``：把 answer 拆成 atomic claims 列表，每条标出所引用的 [n]
2. ``verify_claims``：拿每条 claim + 对应证据片段，逐条判 supported/partial/unsupported

设计约束：
- 输入**不含原 question**（防止 LLM 站在 QA agent 的立场为之辩护）
- temperature=0 + JSON 强约束
- 输出有任何字段缺失 / JSON 解析失败 → 抛 ValueError，由 committee 兜底降级为 skipped
"""
from __future__ import annotations

import json
import re
from typing import Any

from ...llm import get_client
from ...schemas.qa import QAContextItem
from ...schemas.verification import ClaimVerdict, VerifiedClaim


# ---------------- prompts ----------------

_SPLIT_SYS = """你是一名"事实拆分员"。

你的任务：把给定的答复文本拆成若干条**原子事实点（atomic claim）**。

规则：
1. 一条 claim 必须是一个独立、可被证据证伪的陈述（不要把多个事实塞进一条）。
2. 引言、客套话、章节标题、纯连接词 → 不拆。
3. 每条 claim 必须记录它在原答复中引用的编号 [n]；如果该 claim 在原答复中没有 [n]，cited 字段填空数组 []。
4. 严格按下述 JSON Schema 输出，不要任何解释文字、不要 Markdown 包裹。

输出 JSON：
{
  "claims": [
    {"claim": "原子事实点的简洁陈述", "cited": [1, 3]},
    {"claim": "...", "cited": []}
  ]
}
"""

_VERIFY_SYS = """你是一名严格、保守的"证据审核员"。

你的任务：判断每条 claim 是否能从给定的证据片段中**直接得出**。

判定规则（必须从严）：
- supported   ：证据明确、完整支持 claim（每个细节都能在证据中找到）
- partial     ：证据部分支持（如 claim 说"红黑树调度"，证据只见调度但没见红黑树）
- unsupported ：证据明确不支持，或证据中根本看不到此事实
- unverifiable：claim 引用的编号在证据里缺失 / 证据格式异常无法判读

特别注意：
- 严禁基于"常识"或"行业惯例"判 supported。证据没说就是没说。
- evidence_quote 字段必须从给定证据中**逐字截取**关键句（≤80 字），不要改写。
- 如果给的多条证据都不沾边，应判 unsupported 而非 unverifiable。

严格按下述 JSON Schema 输出，不要任何解释文字、不要 Markdown 包裹：

{
  "results": [
    {
      "claim_index": 0,
      "verdict": "supported|partial|unsupported|unverifiable",
      "reason": "一句话说明判定依据（≤60 字）",
      "evidence_quote": "从证据中逐字截取的关键句（≤80 字，没有就留空）"
    }
  ]
}
"""


# ---------------- 工具 ----------------

_JSON_BLOCK_RE = re.compile(r"\{[\s\S]*\}")


def _parse_json(text: str) -> dict[str, Any]:
    """容错 JSON 解析：先直接 loads，失败则正则抠最外层 {}。"""
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = _JSON_BLOCK_RE.search(text)
    if not m:
        raise ValueError(f"无法解析 verifier 返回的 JSON: {text[:200]!r}")
    return json.loads(m.group(0))


def _build_evidence_block(items: list[QAContextItem]) -> str:
    """把全部 sources 拼成"[n] 标题: body"，给 verifier 看。"""
    lines: list[str] = []
    for i, it in enumerate(items, 1):
        lines.append(f"[{i}] {it.title}")
        lines.append(it.body)
        lines.append("")
    return "\n".join(lines)


# ---------------- 公开 API ----------------

def split_claims(answer: str, max_tokens: int = 800) -> tuple[list[dict[str, Any]], str, dict]:
    """第 1 跳：拆 claims。

    Returns
    -------
    (claims, model, usage)  claims 形如 [{"claim": "...", "cited": [1,2]}, ...]
    """
    client = get_client()
    user_msg = f"请将以下答复拆成原子事实点：\n\n---\n{answer}\n---"
    result = client.chat_full(
        [
            {"role": "system", "content": _SPLIT_SYS},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.0,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    data = _parse_json(result["answer"])
    claims = data.get("claims") or []
    if not isinstance(claims, list):
        raise ValueError(f"split_claims 返回 claims 字段非 list: {type(claims)}")
    cleaned: list[dict[str, Any]] = []
    for c in claims:
        if not isinstance(c, dict):
            continue
        txt = (c.get("claim") or "").strip()
        if not txt:
            continue
        cited_raw = c.get("cited") or []
        cited = [int(x) for x in cited_raw if str(x).isdigit()]
        cleaned.append({"claim": txt, "cited": cited})
    return cleaned, result.get("model", ""), result.get("usage") or {}


def verify_claims(
    claims: list[dict[str, Any]],
    items: list[QAContextItem],
    max_tokens: int = 1500,
) -> tuple[list[VerifiedClaim], str, dict]:
    """第 2 跳：逐条核验。

    Returns
    -------
    (verified_claims, model, usage)
    """
    if not claims:
        return [], "", {}

    evidence_block = _build_evidence_block(items)
    claims_block = "\n".join(
        f"{i}. {c['claim']}  (cited={c['cited']})"
        for i, c in enumerate(claims)
    )

    user_msg = (
        "证据片段（每段以 [n] 编号标识）：\n\n"
        f"{evidence_block}\n\n"
        "==========\n\n"
        f"待核验的 {len(claims)} 条 claim：\n{claims_block}\n\n"
        "请对每条 claim 给出 verdict、reason 和 evidence_quote。"
    )

    client = get_client()
    result = client.chat_full(
        [
            {"role": "system", "content": _VERIFY_SYS},
            {"role": "user", "content": user_msg},
        ],
        temperature=0.0,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )
    data = _parse_json(result["answer"])
    results = data.get("results") or []
    if not isinstance(results, list):
        raise ValueError(f"verify_claims 返回 results 非 list: {type(results)}")

    by_idx: dict[int, dict[str, Any]] = {}
    for r in results:
        if not isinstance(r, dict):
            continue
        try:
            idx = int(r.get("claim_index"))
        except (TypeError, ValueError):
            continue
        by_idx[idx] = r

    valid_verdicts: set[ClaimVerdict] = {"supported", "partial", "unsupported", "unverifiable"}
    out: list[VerifiedClaim] = []
    for i, c in enumerate(claims):
        r = by_idx.get(i, {})
        verdict_raw = (r.get("verdict") or "unverifiable").strip().lower()
        verdict: ClaimVerdict = verdict_raw if verdict_raw in valid_verdicts else "unverifiable"
        out.append(VerifiedClaim(
            claim=c["claim"],
            cited_indices=c["cited"],
            verdict=verdict,
            reason=(r.get("reason") or "").strip()[:200],
            evidence_quote=(r.get("evidence_quote") or "").strip()[:200],
        ))
    return out, result.get("model", ""), result.get("usage") or {}
