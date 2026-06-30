"""L1 QuickProfile：秒级输出仓库画像。

包含：
- 语言占比 + LOC
- 构建系统
- 架构识别
- 基线模板识别
- Git 开发历史（commits/贡献者/时间跨度）

设计：复用一次 ScanResult，避免重复 walk。
"""
from __future__ import annotations

import re
import subprocess
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from ..logging import logger
from ..schemas import (
    Basics,
    BuildSystem,
    Commit,
    DevHistory,
    Evidence,
    LanguageStat,
)
from .contract import DetectBaseTemplateOut
from .core import LANG_BY_EXT, ScanResult, safe_read
from .template_fingerprints import FINGERPRINTS

ARCH_PATTERNS = [
    ("riscv64", re.compile(r"riscv64|rv64|RISC-V\s*64|riscv64gc|riscv64imac", re.I)),
    ("riscv32", re.compile(r"riscv32|rv32(?![a-z])", re.I)),
    ("x86_64", re.compile(r"x86_64|amd64", re.I)),
    ("aarch64", re.compile(r"aarch64|arm64", re.I)),
    ("loongarch64", re.compile(r"loongarch64|loongarch", re.I)),
]


# ---------- 语言 / LOC ----------

# loc 统计只读源代码语言；其它（toml/md/makefile）只算文件
_LOC_LANGS = {"Rust", "C", "C++", "Asm", "Python", "Shell", "Go", "Zig", "LinkerScript"}

# 单文件 loc 计数最大读取字节（再大也不会更准）
_LOC_MAX_BYTES = 256_000


def _count_lines_fast(path: Path, max_bytes: int = _LOC_MAX_BYTES) -> int:
    """快速行数：二进制方式 count(b'\\n')，避免 utf-8 decode。"""
    try:
        size = path.stat().st_size
        if size == 0:
            return 0
        with open(path, "rb") as fh:
            data = fh.read(max_bytes)
        n = data.count(b"\n")
        # 末尾无换行也算 1 行
        return n + (1 if data and not data.endswith(b"\n") else 0)
    except OSError:
        return 0


def _languages_and_loc(scan: ScanResult) -> tuple[list[LanguageStat], int]:
    loc_by_lang: dict[str, int] = defaultdict(int)
    for f in scan.files:
        lang = LANG_BY_EXT.get(f.ext)
        if not lang or lang not in _LOC_LANGS:
            continue
        loc_by_lang[lang] += _count_lines_fast(f.path)

    total = sum(loc_by_lang.values())
    langs = [
        LanguageStat(language=k, loc=v, percent=round(v / total * 100, 2) if total else 0.0)
        for k, v in sorted(loc_by_lang.items(), key=lambda x: -x[1])
    ]
    return langs, total


# ---------- Build system ----------

def _detect_build(scan: ScanResult) -> BuildSystem:
    rel_set = {f.rel for f in scan.files}
    flags = {
        "cargo": any(p.endswith("Cargo.toml") for p in rel_set),
        "xmake": any(p.endswith("xmake.lua") for p in rel_set),
        "cmake": any(p.endswith("CMakeLists.txt") for p in rel_set),
        "meson": any(p.endswith("meson.build") for p in rel_set),
        "make": any(p.endswith("Makefile") or p.endswith("makefile") for p in rel_set),
    }
    # 优先级
    for k in ("cargo", "xmake", "cmake", "meson", "make"):
        if flags[k]:
            kind: str = k
            break
    else:
        kind = "unknown"

    build_files = sorted(
        p for p in rel_set
        if p.endswith(("Cargo.toml", "Makefile", "makefile", "CMakeLists.txt", "xmake.lua", "meson.build"))
    )[:20]
    return BuildSystem(kind=kind, files=build_files)  # type: ignore[arg-type]


# ---------- Arch ----------

def _detect_arch(scan: ScanResult) -> list[str]:
    candidates = [
        f for f in scan.files
        if f.ext in {".toml", ".json", ".cfg", ".ld", ".lds", ".md"}
        or f.rel.endswith(("Makefile", "makefile"))
    ]
    # 限制读取数量（性能）
    hits: Counter[str] = Counter()
    for f in candidates[:150]:
        text = safe_read(f.path)
        if not text:
            continue
        for arch, pat in ARCH_PATTERNS:
            if pat.search(text):
                hits[arch] += 1
    return [a for a, _ in hits.most_common()] or ["other"]


# ---------- Base template ----------

def _detect_template(scan: ScanResult) -> DetectBaseTemplateOut:
    rels = [f.rel for f in scan.files]
    rels_l = [r.lower() for r in rels]

    text_files = [
        f for f in scan.files
        if f.rel.lower().endswith(("readme.md", "readme", "cargo.toml", "main.rs", "main.c"))
    ][:30]
    combined = "\n".join(safe_read(f.path) for f in text_files).lower()

    best: tuple[str, int, list[Evidence]] = ("unknown", 0, [])
    for fp in FINGERPRINTS:
        score = 0
        evid: list[Evidence] = []

        for hint in fp.file_hints:
            hint_l = hint.lower()
            for rel_l, rel in zip(rels_l, rels):
                if hint_l in rel_l:
                    score += 2
                    evid.append(Evidence(file=rel, start_line=1, end_line=1))
                    break

        for hint in fp.text_hints:
            if hint.lower() in combined:
                score += 1
                # 找出现位置
                for f in text_files:
                    text = safe_read(f.path)
                    if hint.lower() in text.lower():
                        line_no = next(
                            (i + 1 for i, line in enumerate(text.splitlines())
                             if hint.lower() in line.lower()),
                            1,
                        )
                        evid.append(Evidence(file=f.rel, start_line=line_no, end_line=line_no))
                        break

        if score > best[1]:
            best = (fp.name, score, evid[:5])

    name, score, evid = best
    if score == 0:
        return DetectBaseTemplateOut(template="unknown", confidence="low", evidence=[])
    confidence = "high" if score >= 4 else ("medium" if score >= 2 else "low")
    return DetectBaseTemplateOut(template=name, confidence=confidence, evidence=evid)  # type: ignore[arg-type]


# ---------- Git history ----------

def _git(args: list[str], cwd: Path, timeout: int = 15) -> str:
    try:
        r = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout
        )
        return r.stdout
    except Exception:
        return ""


def _dev_history(repo_root: Path) -> DevHistory:
    log = _git(["log", "--pretty=format:%H%x09%ae%x09%aI%x09%s"], repo_root)
    commits: list[Commit] = []
    authors: set[str] = set()
    for line in log.splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        sha, email, iso, msg = parts[0], parts[1], parts[2], "\t".join(parts[3:])
        authors.add(email)
        try:
            ts = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        except ValueError:
            continue
        commits.append(
            Commit(sha=sha, author_email=email, timestamp=ts, message_first_line=msg[:200])
        )

    first = min((c.timestamp for c in commits), default=None)
    last = max((c.timestamp for c in commits), default=None)
    commits_sorted = sorted(commits, key=lambda c: c.timestamp)
    milestones = commits_sorted[-10:]

    return DevHistory(
        commits_total=len(commits),
        contributors_total=len(authors),
        first_commit_at=first,
        last_commit_at=last,
        milestones=milestones,
    )


# ---------- 顶层 ----------

def run(scan: ScanResult) -> tuple[Basics, DevHistory]:
    """L1：用一次 walk 的结果，产出 Basics + DevHistory。"""
    logger.debug(f"L1 start: {scan.root}")

    langs, total_loc = _languages_and_loc(scan)
    build = _detect_build(scan)
    arch = _detect_arch(scan)
    tpl = _detect_template(scan)
    hist = _dev_history(scan.root)

    basics = Basics(
        languages=langs,
        total_loc=total_loc,
        arch=arch,  # type: ignore[arg-type]
        build=build,
        base_template=tpl.template if tpl.template != "unknown" else None,
        base_template_evidence=tpl.evidence,
    )
    return basics, hist
