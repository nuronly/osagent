"""Analyzer 公共工具：文件遍历、安全读、SKIP 规则、体量保护。

设计要点：
- 一次 walk，所有 L1/L2/L3 共用结果（避免重复 IO）；
- 强目录剪枝（os.walk 原地修改 dirnames）；
- 强文件数/单文件大小上限（巨型仓库不拖垮分析器）；
- 时间预算（每个阶段独立限制）。
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..logging import logger

# ========== 常量 ==========

# 文件后缀 -> 语言
LANG_BY_EXT: dict[str, str] = {
    ".rs": "Rust", ".c": "C", ".h": "C", ".cpp": "C++", ".cc": "C++", ".hpp": "C++",
    ".S": "Asm", ".s": "Asm", ".asm": "Asm",
    ".py": "Python", ".sh": "Shell", ".go": "Go", ".zig": "Zig",
    ".toml": "TOML", ".md": "Markdown", ".mk": "Makefile",
    ".ld": "LinkerScript", ".lds": "LinkerScript",
}

# 我们关心的源代码后缀（用于代码量统计/扫描）
SOURCE_EXTS = {".rs", ".c", ".h", ".cpp", ".cc", ".hpp", ".S", ".s", ".asm"}

# 目录黑名单（不进入）
SKIP_DIR_NAMES: set[str] = {
    # 版本控制 / IDE / 构建产物
    "target", "build", "out", "node_modules", "__pycache__", "dist", ".cache",
    # 第三方依赖 / vendor
    "dependencies", "vendor", "third_party", "third-party", "thirdparty",
    "external", "externals", "deps", "vcpkg", "submodules",
    # 巨型内核 / 工具链源（出现往往是 sdk 整套塞进来）
    "linux", "linux-kernel", "llvm", "llvm-project", "gcc",
    "musl", "newlib", "glibc", "binutils",
    # 测试 / sdk / 文档
    "testcase", "testcases", "test-suite", "sdk", "user_lib",
    "docs", "doc", "documentation",
}

# 体量保护
MAX_FILES = 6000                # 单仓库最多扫描的文件数
MAX_FILE_BYTES = 1_000_000      # 单文件超过 1MB 不读
MAX_BYTES_TOTAL = 60_000_000    # 累计读取超过 60MB 直接停（异常仓库防爆）


# ========== 数据结构 ==========

@dataclass
class FileItem:
    """一条文件记录（一次扫描，所有阶段共用）。"""
    path: Path                  # 绝对路径
    rel: str                    # 相对仓库根的路径（POSIX 风格）
    ext: str
    size: int
    is_source: bool             # 是否是源码（用于 loc）


@dataclass
class ScanResult:
    """walk 的结果。"""
    root: Path
    files: list[FileItem] = field(default_factory=list)
    truncated: bool = False     # 是否因为体量保护被截断
    elapsed: float = 0.0
    bytes_read: int = 0         # walk 本身不读，留给后续阶段累加


# ========== walk ==========

def walk_files(root: Path, *, max_files: int = MAX_FILES) -> ScanResult:
    """一次遍历，得到所有候选文件。

    返回的文件列表已经做了：
    - SKIP_DIR_NAMES 目录剪枝
    - 隐藏目录（.git/.vscode 等）剪枝
    - 上限截断
    - 仅保留我们认识的后缀 + 关键根文件（README/Cargo.toml/Makefile 等）
    """
    t0 = time.time()
    keep_filenames = {
        "readme.md", "readme", "makefile", "cargo.toml",
        "cmakelists.txt", "xmake.lua", "meson.build", "build.rs",
        "rust-toolchain", "rust-toolchain.toml",
    }

    items: list[FileItem] = []
    truncated = False

    for dirpath, dirnames, filenames in os.walk(root):
        # 原地剪枝
        dirnames[:] = [
            d for d in dirnames
            if d not in SKIP_DIR_NAMES and not d.startswith(".")
        ]

        for fn in filenames:
            ext = Path(fn).suffix
            fn_l = fn.lower()
            if ext not in LANG_BY_EXT and fn_l not in keep_filenames:
                continue
            full = Path(dirpath) / fn
            try:
                size = full.stat().st_size
            except OSError:
                continue
            rel = str(full.relative_to(root)).replace(os.sep, "/")
            items.append(
                FileItem(
                    path=full,
                    rel=rel,
                    ext=ext,
                    size=size,
                    is_source=ext in SOURCE_EXTS,
                )
            )
            if len(items) >= max_files:
                truncated = True
                break
        if truncated:
            break

    elapsed = time.time() - t0
    if truncated:
        logger.warning(
            f"walk: 文件数达上限 {max_files}，已截断（疑似包含 vendor/巨型库的仓库）"
        )
    logger.debug(f"walk: {len(items)} files in {elapsed:.2f}s, root={root}")
    return ScanResult(root=root, files=items, truncated=truncated, elapsed=elapsed)


# ========== safe read ==========

def safe_read(path: Path, *, max_bytes: int = MAX_FILE_BYTES) -> str:
    """安全读文本（超大/二进制 → 空串）。"""
    try:
        if path.stat().st_size > max_bytes:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except (OSError, UnicodeError):
        return ""


# ========== 时间预算 ==========

class TimeBudget:
    """简单时间预算 helper：超过预算时 should_stop() 返回 True。"""

    def __init__(self, seconds: float) -> None:
        self.budget = seconds
        self.t0 = time.time()

    @property
    def elapsed(self) -> float:
        return time.time() - self.t0

    def should_stop(self) -> bool:
        return self.elapsed >= self.budget


# ========== 进度回调 ==========

ProgressCallback = "callable"  # signature: (stage: str, msg: str, pct: int) -> None


def noop_progress(stage: str, msg: str, pct: int) -> None:
    """默认进度回调：什么都不做。"""
    return None
