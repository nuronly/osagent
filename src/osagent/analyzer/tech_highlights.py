"""技术特点 + 项目总结：基于事实表反推出 6-8 条人类可读总结。

完全基于事实，不调 LLM；
- tech_highlights: 每识别到的关键子系统对应一条
- project_summary: 简短的"实现了 X"风格列表

输入：kernel_features（含 feature_tags / data_structures / key_functions），syscalls
"""
from __future__ import annotations

from collections import OrderedDict

from ..schemas import KernelFeature, SyscallTable, TechHighlight


# 子系统 -> (技术特点标题, 默认要点 generator)
_HIGHLIGHT_TEMPLATES: list[tuple[str, str, str]] = [
    # feature, title, summary_template (含 {tags}/{nfiles})
    ("memory",     "内存管理",       "实现了内存管理子系统，覆盖 {nfiles} 个源文件"),
    ("process",    "进程与线程管理", "实现了进程/线程管理与上下文切换，覆盖 {nfiles} 个源文件"),
    ("scheduler",  "任务调度",       "实现了任务调度器，覆盖 {nfiles} 个源文件"),
    ("syscall",    "系统调用接口",   "实现了系统调用接口层，覆盖 {nfiles} 个源文件"),
    ("filesystem", "文件系统",       "实现了文件系统层，覆盖 {nfiles} 个源文件"),
    ("driver",     "设备驱动",       "实现了设备驱动框架，覆盖 {nfiles} 个源文件"),
    ("ipc",        "进程间通信与同步", "实现了 IPC 与同步机制，覆盖 {nfiles} 个源文件"),
    ("trap",       "中断与异常",     "实现了中断与异常处理，覆盖 {nfiles} 个源文件"),
    ("signal",     "信号机制",       "实现了信号机制，覆盖 {nfiles} 个源文件"),
    ("smp",        "多核支持",       "支持 SMP 多核环境，覆盖 {nfiles} 个源文件"),
    ("network",    "网络协议栈",     "实现了网络协议栈，覆盖 {nfiles} 个源文件"),
    ("boot",       "引导与初始化",   "实现了系统引导与初始化流程，覆盖 {nfiles} 个源文件"),
]


def build_tech_highlights(features: list[KernelFeature], syscalls: SyscallTable) -> list[TechHighlight]:
    """按子系统命中情况生成技术特点列表，每个 highlight 用 feature_tags 作为 bullets。"""
    by_feature = {f.feature: f for f in features}
    highlights: list[TechHighlight] = []

    for feat, title, summary_tpl in _HIGHLIGHT_TEMPLATES:
        kf = by_feature.get(feat)
        if not kf:
            continue
        bullets = list(kf.feature_tags)
        # 兜底：用 key_functions 前 3 个
        if not bullets and kf.key_functions:
            bullets = [f"关键函数 `{name}` 已实现" for name in kf.key_functions[:3]]
        # 兜底 2：用 data_structures
        if not bullets and kf.data_structures:
            bullets = [f"定义关键数据结构 `{name}`" for name in kf.data_structures[:3]]
        highlights.append(
            TechHighlight(
                title=title,
                summary=summary_tpl.format(nfiles=len(kf.files)),
                bullets=bullets[:6],
            )
        )

    # 末尾：根据 syscall 分类追加一条"系统调用覆盖度"
    if syscalls.count > 0:
        cat_bits = []
        for cat, n in (syscalls.by_category or {}).items():
            if n > 0:
                from .syscall_dict import CATEGORY_LABEL_ZH
                cat_bits.append(f"{CATEGORY_LABEL_ZH.get(cat, cat)} {n} 个")
        highlights.append(
            TechHighlight(
                title="系统调用覆盖",
                summary=f"共识别 {syscalls.count} 个系统调用接口",
                bullets=cat_bits[:8],
            )
        )

    return highlights


def build_project_summary(features: list[KernelFeature], syscalls: SyscallTable,
                          *, repo_id: str = "") -> list[str]:
    """生成"项目总结"6-8 条要点。"""
    by_feature = {f.feature: f for f in features}
    lines: list[str] = []

    if "boot" in by_feature:
        lines.append("引导系统：实现了完整的系统引导流程，包括硬件初始化与内核加载")
    if "memory" in by_feature:
        tags = by_feature["memory"].feature_tags
        if any("页表" in t or "VMA" in t for t in tags):
            lines.append("内存管理：实现了带虚拟内存与多级页表的内存管理子系统")
        else:
            lines.append("内存管理：实现了内存分配与回收基础设施")
    if "process" in by_feature or "scheduler" in by_feature:
        lines.append("进程/线程管理：实现了任务管理与调度，支持上下文切换")
    if "syscall" in by_feature:
        lines.append(f"系统调用：实现了系统调用接口层，识别 {syscalls.count} 个调用")
    if "filesystem" in by_feature or "vfs" in by_feature:
        tags = (by_feature.get("filesystem") or by_feature.get("vfs")).feature_tags
        if "VFS 抽象层" in tags:
            lines.append("文件系统：实现了 VFS 抽象层，支持多文件系统接入")
        else:
            lines.append("文件系统：实现了文件系统抽象，支持文件与目录操作")
    if "driver" in by_feature:
        lines.append("设备驱动：实现了设备驱动框架，支持多种外设")
    if "ipc" in by_feature:
        lines.append("IPC/同步：实现了管道、信号量、互斥锁等同步与通信机制")
    if "trap" in by_feature:
        lines.append("中断与异常：实现了中断/异常处理框架")
    if "smp" in by_feature:
        lines.append("多核支持：具备 SMP 多核运行能力")
    if "network" in by_feature:
        lines.append("网络：实现了网络协议栈，支持基础网络通信")

    return lines[:8]
