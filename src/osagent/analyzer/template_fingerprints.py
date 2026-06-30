"""基线模板指纹库。

识别仓库是否衍生自 rCore / xv6-k210 / uCore 等基线模板。
做法：基于"指纹文件 + 关键字符串"的简单规则，命中即返回（高置信度）。

注：v1 用启发式规则；v2 可升级到 AST 级或 commit 历史溯源。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TemplateFingerprint:
    name: str
    # 任一文件路径子串命中即可
    file_hints: tuple[str, ...] = ()
    # 任一文本片段在 README / Cargo.toml / main.rs 中命中即可
    text_hints: tuple[str, ...] = ()
    notes: str = ""


FINGERPRINTS: tuple[TemplateFingerprint, ...] = (
    TemplateFingerprint(
        name="rCore-Tutorial-v3",
        file_hints=("os/src/main.rs", "os/Makefile", "os/src/console.rs"),
        text_hints=(
            "rCore-Tutorial",
            "rcore-tutorial-v3",
            "rust-osdev",
            "use_sbi",
            'sbi_rt',
        ),
        notes="清华 rCore 教程模板（最常见的 Rust RISC-V 内核基线）",
    ),
    TemplateFingerprint(
        name="rCore",
        file_hints=("rCore", "rcore"),
        text_hints=("rcore", "RCore"),
        notes="rCore 系列（含变体）",
    ),
    TemplateFingerprint(
        name="xv6-k210",
        file_hints=("xv6-k210", "kernel/main.c", "kernel/proc.c", "kernel/trap.c"),
        text_hints=("xv6-k210", "xv6", "MIT xv6"),
        notes="MIT xv6 的 K210 / RISC-V 移植",
    ),
    TemplateFingerprint(
        name="xv6-riscv",
        file_hints=("kernel/main.c", "kernel/syscall.c", "kernel/proc.c"),
        text_hints=("xv6-riscv", "xv6 riscv"),
    ),
    TemplateFingerprint(
        name="uCore",
        file_hints=("ucore", "uCore"),
        text_hints=("uCore", "ucore_plus", "清华操作系统"),
    ),
    TemplateFingerprint(
        name="uCore-SMP",
        file_hints=("ucore-smp", "uCore-SMP"),
        text_hints=("uCore-SMP", "uCore_SMP"),
    ),
    TemplateFingerprint(
        name="blog_os",
        file_hints=("blog_os",),
        text_hints=("blog_os", "phil-opp"),
        notes="Philipp Oppermann 博客系列教程",
    ),
)
