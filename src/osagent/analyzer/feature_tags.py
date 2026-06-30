"""功能特征标签：在子系统命中的文件内容里做关键字匹配，输出中文标签。

为什么独立成文件：
- 子系统命中是"按路径"（粗粒度），feature_tags 是"按内容"（细粒度）；
- 标签是面向人的可读标签，要能直接落到报告里；
- 单独配置便于以后扩展每个子系统的精细识别。

策略：扫每个子系统的命中文件（最多 N 个），命中关键字就打标签。
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from .core import safe_read

# (feature_name) -> [(关键字 tuple, 中文标签)]
# 关键字大小写不敏感（统一 lower 后匹配）；命中其中任一即打标签。
_FEATURE_TAG_RULES: dict[str, list[tuple[tuple[str, ...], str]]] = {
    "memory": [
        (("buddy_alloc", "buddy_system", "buddy"), "buddy 分配器"),
        (("slab", "slub", "kmem_cache"), "slab/SLUB 分配器"),
        (("page_alloc", "alloc_page", "frame_alloc", "alloc_frame"), "页帧分配"),
        (("page_table", "pagetable", "pgtable", "pml4", "pte_t"), "多级页表"),
        (("kmalloc", "kfree", "alloc_zeroed"), "内核堆分配"),
        (("vm_area", "vma", "mmap_region"), "虚拟内存区域 (VMA)"),
        (("copy_on_write", "cow", "page_fault"), "缺页与 COW"),
        (("address_space",), "地址空间抽象"),
        (("tlb_flush", "flush_tlb"), "TLB 维护"),
    ],
    "scheduler": [
        (("round_robin", "time_slice"), "时间片轮转"),
        (("priority",), "优先级调度"),
        (("rbtree", "cfs"), "CFS 红黑树"),
        (("smp_balance", "load_balance"), "多核负载均衡"),
        (("idle_task", "idle_thread"), "Idle 任务"),
        (("schedule()", "do_schedule", "fn schedule"), "调度入口"),
    ],
    "process": [
        (("fork", "sys_fork", "do_fork"), "fork/clone"),
        (("exec", "do_exec", "load_elf"), "exec/ELF 加载"),
        (("exit", "do_exit"), "进程退出"),
        (("wait", "do_wait", "waitpid"), "wait 回收"),
        (("task_struct", "pcb"), "进程控制块"),
        (("thread", "tid"), "线程支持"),
        (("context_switch", "switch_to"), "上下文切换"),
    ],
    "syscall": [
        (("syscall_table", "sys_call_table"), "系统调用表"),
        (("trap_handler", "exception_handler"), "陷入处理"),
        (("dispatcher", "syscall_dispatch"), "系统调用分发"),
        (("ecall", "svc", "syscall_no"), "用户态陷入"),
    ],
    "filesystem": [
        (("fat32", "fat16"), "FAT 文件系统"),
        (("ext2", "ext4"), "ext 文件系统"),
        (("vfs",), "VFS 抽象层"),
        (("inode", "dentry"), "inode/dentry 抽象"),
        (("block_cache", "buffer_cache"), "块缓存"),
        (("page_cache",), "页缓存"),
        (("mount", "umount"), "挂载/卸载"),
        (("file_descriptor", "fd_table"), "文件描述符表"),
        (("dir", "dirent", "directory"), "目录管理"),
    ],
    "driver": [
        (("virtio_blk", "virtio_net"), "VirtIO 设备"),
        (("uart", "ns16550", "16550"), "UART 串口"),
        (("plic",), "PLIC 中断控制器"),
        (("clint",), "CLINT 时钟"),
        (("sdcard", "sd_card", "spi_sd"), "SD 卡驱动"),
        (("gpio",), "GPIO 驱动"),
        (("device_tree", "fdt", "dtb"), "设备树解析"),
    ],
    "ipc": [
        (("pipe",), "管道"),
        (("shm", "shared_memory"), "共享内存"),
        (("mqueue", "message_queue"), "消息队列"),
        (("semaphore", "sem_post", "sem_wait"), "信号量"),
        (("mutex", "lock_mutex"), "互斥锁"),
    ],
    "trap": [
        (("interrupt", "irq_handler"), "中断处理"),
        (("exception", "trap_handler"), "异常处理"),
        (("page_fault",), "缺页异常"),
        (("stvec", "mtvec", "idt"), "中断向量表"),
    ],
    "boot": [
        (("entry.s", "_start", "boot.s"), "汇编入口"),
        (("init_kernel", "kernel_main", "kmain"), "内核 main"),
        (("linker.ld", "memory.x"), "链接脚本"),
        (("opensbi", "sbi_call"), "SBI 接口"),
    ],
    "smp": [
        (("hart_id", "cpu_id", "smp_id"), "多核 ID"),
        (("ipi",), "核间中断 (IPI)"),
        (("per_cpu", "percpu"), "Per-CPU 数据"),
    ],
    "signal": [
        (("sigaction", "do_signal"), "信号注册与递送"),
        (("rt_sig", "sigset"), "实时信号"),
        (("signal_stack", "sigaltstack"), "备用信号栈"),
    ],
    "virtio": [
        (("virtqueue", "virtio_ring"), "Virtqueue"),
        (("virtio_blk",), "VirtIO-Blk"),
        (("virtio_net",), "VirtIO-Net"),
    ],
    "network": [
        (("tcp",), "TCP 协议"),
        (("udp",), "UDP 协议"),
        (("lwip",), "lwIP 协议栈"),
        (("socket",), "Socket 接口"),
    ],
}


def detect_tags_for_feature(feature: str, files: list[str], root: Path,
                            *, max_files: int = 8, max_bytes_each: int = 60_000) -> list[str]:
    """对一个子系统命中的文件做关键字扫描，返回去重后的中文标签列表。"""
    rules = _FEATURE_TAG_RULES.get(feature)
    if not rules:
        return []

    tags: list[str] = []
    seen: set[str] = set()

    for rel in files[:max_files]:
        path = root / rel
        try:
            text = safe_read(path, max_bytes=max_bytes_each)
        except Exception:
            continue
        if not text:
            continue
        text_l = text.lower()
        for kws, label in rules:
            if label in seen:
                continue
            if any(kw in text_l for kw in kws):
                tags.append(label)
                seen.add(label)
    return tags
