"""引用警察（纯规则，无 LLM）。

只做形式审查，**不判语义**：
- answer 里出现的 [n] 编号是否都在 sources 范围内？
- 答复里明文出现的文件路径，sources 里是不是真有？
- 答复里明文出现的行号区间，是否落在 sources 给出的行号范围内？

任一项失败 → 整个 VerificationStatus 必为 rejected。
"""
from __future__ import annotations

import re
from typing import Iterable

from ...schemas.qa import QASource
from ...schemas.verification import CitationCheck


_CITE_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
_LINE_RE = re.compile(r"([\w./\-]+\.\w+):L?(\d+)(?:\s*[-\u2013]\s*L?(\d+))?")


def _all_cited(answer: str) -> list[int]:
    out: list[int] = []
    for m in _CITE_RE.finditer(answer):
        for piece in m.group(1).split(","):
            try:
                out.append(int(piece.strip()))
            except ValueError:
                continue
    return out


def check(answer: str, sources: list[QASource]) -> list[CitationCheck]:
    """对 answer 里出现的每个 [n] 做形式审查。"""
    checks: list[CitationCheck] = []
    n_sources = len(sources)
    cited = _all_cited(answer)

    seen: set[int] = set()
    for idx in cited:
        if idx in seen:
            continue
        seen.add(idx)
        if idx < 1 or idx > n_sources:
            checks.append(CitationCheck(
                index=idx,
                ok=False,
                reason=f"out_of_range: 引用编号 [{idx}] 超出 sources(1..{n_sources})",
            ))
        else:
            checks.append(CitationCheck(index=idx, ok=True))

    source_files: dict[str, tuple[int | None, int | None]] = {}
    for s in sources:
        if s.file:
            source_files[s.file] = (s.start_line, s.end_line)

    for m in _LINE_RE.finditer(answer):
        fname, start_s, end_s = m.group(1), m.group(2), m.group(3)
        if fname not in source_files:
            checks.append(CitationCheck(
                index=-1,
                ok=False,
                reason=f"no_file_match: 答复出现 '{fname}:{start_s}' 但 sources 中无此文件",
            ))
            continue
        s_start, s_end = source_files[fname]
        if s_start is None or s_end is None:
            continue
        try:
            ans_start = int(start_s)
            ans_end = int(end_s) if end_s else ans_start
        except ValueError:
            continue
        if ans_start < s_start or ans_end > s_end:
            checks.append(CitationCheck(
                index=-1,
                ok=False,
                reason=(
                    f"line_out_of_range: '{fname}:{ans_start}-{ans_end}' "
                    f"超出 source 区间 {s_start}-{s_end}"
                ),
            ))

    return checks


def all_passed(checks: Iterable[CitationCheck]) -> bool:
    return all(c.ok for c in checks)
