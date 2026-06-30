"""QA agent：retrieve → prompt → LLM → 解析引用 → QAResponse。

仅做"开放问答"，不做工具调用、不做多轮对话；
所有抗幻觉约束写在 prompt.py 的 system prompt 里。
"""
from __future__ import annotations

import re
import time

from ..llm import get_client
from ..logging import logger
from ..schemas.qa import (
    QAContextItem,
    QARequest,
    QAResponse,
    QASource,
    TokenUsage,
)
from .prompt import build_messages
from .retriever import retrieve

# 匹配 [1] / [1,2] / [1][2] 这种引用
_CITE_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")


def _parse_cited_indices(answer: str, max_idx: int) -> list[int]:
    """从答复里抠出所有 [n]，返回去重且有序的索引列表（n 从 1 开始）。"""
    seen: list[int] = []
    for m in _CITE_RE.finditer(answer):
        for piece in m.group(1).split(","):
            try:
                n = int(piece.strip())
            except ValueError:
                continue
            if 1 <= n <= max_idx and n not in seen:
                seen.append(n)
    return seen


def _repo_ids_for(req: QARequest) -> list[str]:
    if req.scope == "repo":
        return [req.repo_id] if req.repo_id else []
    if req.scope == "compare":
        return [x for x in (req.repo_id_a, req.repo_id_b) if x]
    return []


def ask(req: QARequest) -> QAResponse:
    """执行一次问答。"""
    t0 = time.time()

    items, warns = retrieve(req)
    repo_ids = _repo_ids_for(req)

    # 没有证据：不发起 LLM 调用，直接给"暂无证据"
    if not items:
        return QAResponse(
            question=req.question,
            scope=req.scope,
            repo_ids=repo_ids,
            answer=(
                "根据现有事实表，暂无足够证据回答该问题。\n\n"
                "原因如下：\n" + "\n".join(f"- {w}" for w in warns or ["未检索到上下文。"])
            ),
            sources=[],
            warnings=warns,
            latency_ms=int((time.time() - t0) * 1000),
        )

    messages = build_messages(req, items)
    context_chars = sum(len(it.body) for it in items)

    try:
        client = get_client()
        result = client.chat_full(
            messages,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
        )
    except Exception as e:
        logger.exception("QA LLM 调用失败")
        return QAResponse(
            question=req.question,
            scope=req.scope,
            repo_ids=repo_ids,
            answer=f"调用 LLM 失败：{e}\n\n但已检索到 {len(items)} 条事实表上下文（见 sources）。",
            sources=[it.source for it in items],
            context_items_used=len(items),
            context_chars=context_chars,
            warnings=warns + [f"LLM 调用失败: {type(e).__name__}: {e}"],
            latency_ms=int((time.time() - t0) * 1000),
        )

    answer: str = result["answer"]
    cited = _parse_cited_indices(answer, len(items))
    used_sources: list[QASource] = []
    if cited:
        # 把 LLM 引用的"稀疏编号"按出现顺序重映射为 1..k，
        # 这样前端 chip 跳转的 idx 和 sources 列表一一对应。
        old_to_new: dict[int, int] = {old: new for new, old in enumerate(cited, start=1)}

        def _repl(m: re.Match) -> str:
            new_nums: list[str] = []
            for piece in m.group(1).split(","):
                try:
                    old = int(piece.strip())
                except ValueError:
                    continue
                if old in old_to_new:
                    new_nums.append(str(old_to_new[old]))
            return "[" + "][".join(new_nums) + "]" if new_nums else m.group(0)

        answer = _CITE_RE.sub(_repl, answer)
        for old in cited:
            used_sources.append(items[old - 1].source)
    else:
        # 没引用 → 全量回传（前端仍能展示证据列表），但加 warning
        used_sources = [it.source for it in items]
        warns = warns + ["LLM 未在答复中标注引用编号 [n]，已回传全部检索条目。"]

    usage = TokenUsage(**{
        k: v for k, v in (result.get("usage") or {}).items()
        if k in {"prompt_tokens", "completion_tokens", "total_tokens"}
    })

    return QAResponse(
        question=req.question,
        scope=req.scope,
        repo_ids=repo_ids,
        answer=answer,
        sources=used_sources,
        context_items_used=len(items),
        context_chars=context_chars,
        model=result.get("model", ""),
        usage=usage,
        latency_ms=int((time.time() - t0) * 1000),
        warnings=warns,
    )
