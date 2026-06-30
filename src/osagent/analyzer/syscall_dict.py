"""Syscall 名 → 分类 + 一句话描述。

策略：
- 内置一份常见 Linux/POSIX syscall 的字典（涵盖 ~100 个），命中就填；
- 名称规范化：strip 前缀 sys_/syscall_id_/__NR_，再 lowercase；
- 未命中则按关键字猜分类，description 留空。

纯查表，零 LLM 调用；保证可复现、可审计。
"""
from __future__ import annotations

from typing import Literal

SyscallCategory = Literal["process", "file", "memory", "sync", "signal", "net", "time", "other"]

# (category, description) 字典
_SYSCALL_DICT: dict[str, tuple[SyscallCategory, str]] = {
    # ===== 进程 / 线程 =====
    "fork":          ("process", "复制当前进程，创建子进程"),
    "vfork":         ("process", "复制进程但与父进程共享地址空间，常配合 exec"),
    "clone":         ("process", "创建新进程或线程，可精细控制共享资源"),
    "clone3":        ("process", "clone 的扩展版本，使用 clone_args 结构传参"),
    "execve":        ("process", "执行新程序，替换当前进程的地址空间"),
    "execveat":      ("process", "相对目录文件描述符执行新程序"),
    "exit":          ("process", "终止当前线程并释放资源"),
    "exit_group":    ("process", "终止线程组内所有线程"),
    "wait4":         ("process", "等待子进程结束，获取退出状态"),
    "waitid":        ("process", "等待指定子进程状态变化"),
    "getpid":        ("process", "获取当前进程 ID"),
    "getppid":       ("process", "获取父进程 ID"),
    "gettid":        ("process", "获取当前线程 ID"),
    "getuid":        ("process", "获取实际用户 ID"),
    "geteuid":       ("process", "获取有效用户 ID"),
    "getgid":        ("process", "获取实际组 ID"),
    "getegid":       ("process", "获取有效组 ID"),
    "setuid":        ("process", "设置实际用户 ID"),
    "setgid":        ("process", "设置实际组 ID"),
    "setsid":        ("process", "创建新会话，使调用进程成为会话首进程"),
    "setpgid":       ("process", "设置进程组 ID"),
    "getpgid":       ("process", "获取进程组 ID"),
    "sched_yield":   ("process", "主动让出 CPU 时间片"),
    "sched_setaffinity": ("process", "设置进程 CPU 亲和性"),
    "sched_getaffinity": ("process", "获取进程 CPU 亲和性"),
    "set_tid_address": ("process", "设置线程 ID 地址，线程退出时清零"),
    "set_robust_list": ("process", "设置 robust 列表，用于线程异常退出唤醒等待者"),
    "prlimit64":     ("process", "查询或设置进程资源限制"),
    "getrusage":     ("process", "获取进程的资源使用情况"),
    "kill":          ("process", "向进程发送信号"),
    "tkill":         ("process", "向特定线程发送信号"),
    "tgkill":        ("process", "向线程组内的特定线程发送信号"),
    "yield":         ("process", "让出 CPU"),

    # ===== 文件 / VFS =====
    "openat":        ("file", "打开（或创建）文件，返回文件描述符"),
    "open":          ("file", "打开文件（旧接口，已被 openat 取代）"),
    "creat":         ("file", "创建文件"),
    "close":         ("file", "关闭文件描述符"),
    "read":          ("file", "从文件描述符读取数据"),
    "write":         ("file", "向文件描述符写入数据"),
    "readv":         ("file", "从文件描述符向多缓冲区读取（scatter read）"),
    "writev":        ("file", "向文件描述符从多缓冲区写入（gather write）"),
    "pread":         ("file", "在指定偏移读取，不更新文件位置"),
    "pwrite":        ("file", "在指定偏移写入，不更新文件位置"),
    "pread64":       ("file", "64 位偏移版本的 pread"),
    "pwrite64":      ("file", "64 位偏移版本的 pwrite"),
    "lseek":         ("file", "调整文件读写位置"),
    "dup":           ("file", "复制文件描述符"),
    "dup2":          ("file", "复制到指定的文件描述符号"),
    "dup3":          ("file", "dup2 加 close-on-exec 标志"),
    "fcntl":         ("file", "操作文件描述符属性"),
    "fcntl64":       ("file", "fcntl 的 64 位版本"),
    "ioctl":         ("file", "向设备发送控制命令"),
    "fstat":         ("file", "获取已打开文件的状态"),
    "fstatat":       ("file", "相对目录获取文件状态"),
    "newfstat":      ("file", "获取文件状态（新接口）"),
    "newfstatat":    ("file", "相对目录获取文件状态（新接口）"),
    "statx":         ("file", "获取扩展文件状态信息"),
    "statfs":        ("file", "获取文件系统状态"),
    "fstatfs":       ("file", "通过 fd 获取文件系统状态"),
    "getdents":      ("file", "读取目录项"),
    "getdents64":    ("file", "读取目录项（64 位接口）"),
    "mkdir":         ("file", "创建目录"),
    "mkdirat":       ("file", "相对目录创建目录"),
    "rmdir":         ("file", "删除空目录"),
    "unlink":        ("file", "删除文件"),
    "unlinkat":      ("file", "相对目录删除文件或目录"),
    "rename":        ("file", "重命名文件"),
    "renameat":      ("file", "相对目录重命名"),
    "renameat2":     ("file", "支持 RENAME_NOREPLACE/EXCHANGE 的 rename"),
    "link":          ("file", "创建硬链接"),
    "linkat":        ("file", "相对目录创建硬链接"),
    "symlink":       ("file", "创建符号链接"),
    "symlinkat":     ("file", "相对目录创建符号链接"),
    "readlink":      ("file", "读取符号链接目标"),
    "readlinkat":    ("file", "相对目录读取符号链接目标"),
    "truncate":      ("file", "按路径截断文件长度"),
    "ftruncate":     ("file", "按 fd 截断文件长度"),
    "ftruncate64":   ("file", "ftruncate 的 64 位版本"),
    "chdir":         ("file", "改变当前工作目录"),
    "fchdir":        ("file", "通过 fd 改变当前工作目录"),
    "getcwd":        ("file", "获取当前工作目录"),
    "chmod":         ("file", "修改文件权限"),
    "fchmod":        ("file", "通过 fd 修改文件权限"),
    "fchmodat":      ("file", "相对目录修改文件权限"),
    "chown":         ("file", "修改文件所有者"),
    "fchown":        ("file", "通过 fd 修改文件所有者"),
    "fchownat":      ("file", "相对目录修改文件所有者"),
    "access":        ("file", "检查文件访问权限"),
    "faccessat":     ("file", "相对目录检查文件访问权限"),
    "faccessat2":    ("file", "支持 flags 的 faccessat"),
    "umask":         ("file", "设置文件创建掩码"),
    "sync":          ("file", "把所有内核缓冲写回磁盘"),
    "fsync":         ("file", "把指定 fd 的数据写回磁盘"),
    "fdatasync":     ("file", "同 fsync 但只同步数据，不含元数据"),
    "mount":         ("file", "挂载文件系统"),
    "umount":        ("file", "卸载文件系统"),
    "umount2":       ("file", "带标志的 umount"),
    "pipe":          ("file", "创建管道"),
    "pipe2":         ("file", "支持 flags 的 pipe"),
    "sendfile":      ("file", "在两个 fd 间零拷贝传输数据"),
    "splice":        ("file", "在两个 fd 间移动数据（零拷贝）"),
    "tee":           ("file", "复制管道数据但不消费"),
    "copy_file_range": ("file", "在两个 fd 间在内核空间复制数据"),
    "poll":          ("file", "等待 fd 集合上的事件"),
    "ppoll":         ("file", "支持时间精度和信号屏蔽的 poll"),
    "select":        ("file", "等待 fd 集合上的事件（旧接口）"),
    "pselect6":      ("file", "支持信号屏蔽的 select"),
    "epoll_create":  ("file", "创建 epoll 实例"),
    "epoll_create1": ("file", "支持 flags 的 epoll_create"),
    "epoll_ctl":     ("file", "向 epoll 实例添加/修改/删除监听项"),
    "epoll_wait":    ("file", "等待 epoll 事件"),
    "epoll_pwait":   ("file", "支持信号屏蔽的 epoll_wait"),

    # ===== 内存 =====
    "brk":           ("memory", "调整数据段顶端，扩展或收缩堆"),
    "sbrk":          ("memory", "相对调整数据段顶端"),
    "mmap":          ("memory", "映射文件或匿名内存到地址空间"),
    "mmap2":         ("memory", "页对齐偏移的 mmap"),
    "mmap_anonymous": ("memory", "映射匿名内存（无后端文件）"),
    "mmap_select_addr": ("memory", "辅助函数：选择 mmap 目标地址"),
    "munmap":        ("memory", "解除内存映射"),
    "mprotect":      ("memory", "修改内存区域的访问权限"),
    "mremap":        ("memory", "调整已有映射的大小或位置"),
    "madvise":       ("memory", "向内核提示内存使用模式"),
    "msync":         ("memory", "把内存映射的修改同步到底层文件"),
    "mlock":         ("memory", "锁定页面到物理内存，禁止换出"),
    "munlock":       ("memory", "解除页面锁定"),
    "membarrier":    ("memory", "插入内存屏障"),
    "shmget":        ("memory", "获取或创建 System V 共享内存段"),
    "shmat":         ("memory", "把共享内存段附加到地址空间"),
    "shmdt":         ("memory", "解除共享内存段附加"),
    "shmctl":        ("memory", "控制 System V 共享内存"),

    # ===== 同步 / 锁 =====
    "futex":         ("sync", "用户空间快速互斥锁的核心系统调用"),
    "futex_waitv":   ("sync", "等待多个 futex 中任一变化"),
    "semget":        ("sync", "获取或创建 System V 信号量集"),
    "semop":         ("sync", "对信号量执行 P/V 操作"),
    "semctl":        ("sync", "控制 System V 信号量"),

    # ===== 信号 =====
    "rt_sigaction":  ("signal", "注册实时信号处理函数"),
    "rt_sigprocmask": ("signal", "设置或查询信号屏蔽字"),
    "rt_sigpending": ("signal", "查询未决信号集"),
    "rt_sigtimedwait": ("signal", "等待指定信号，可带超时"),
    "rt_sigreturn":  ("signal", "信号处理结束后返回原执行流"),
    "rt_sigsuspend": ("signal", "临时替换信号屏蔽字并挂起进程"),
    "sigaltstack":   ("signal", "设置备用信号栈"),
    "signalfd":      ("signal", "通过 fd 接收信号"),

    # ===== 网络 =====
    "socket":        ("net", "创建套接字"),
    "socketpair":    ("net", "创建一对相连的套接字"),
    "bind":          ("net", "绑定套接字到本地地址"),
    "listen":        ("net", "把套接字置为被动监听状态"),
    "accept":        ("net", "接受连入连接"),
    "accept4":       ("net", "支持 flags 的 accept"),
    "connect":       ("net", "发起到远端的连接"),
    "send":          ("net", "通过套接字发送数据"),
    "sendto":        ("net", "向指定地址发送数据"),
    "sendmsg":       ("net", "以消息形式发送数据，支持辅助数据"),
    "recv":          ("net", "通过套接字接收数据"),
    "recvfrom":      ("net", "接收数据并返回发送方地址"),
    "recvmsg":       ("net", "以消息形式接收数据，支持辅助数据"),
    "shutdown":      ("net", "关闭套接字的部分或全部连接"),
    "setsockopt":    ("net", "设置套接字选项"),
    "getsockopt":    ("net", "获取套接字选项"),
    "getsockname":   ("net", "获取套接字本地地址"),
    "getpeername":   ("net", "获取套接字对端地址"),

    # ===== 时间 =====
    "nanosleep":     ("time", "高精度睡眠指定时长"),
    "clock_nanosleep": ("time", "基于指定时钟源高精度睡眠"),
    "clock_gettime": ("time", "获取指定时钟源的时间"),
    "clock_settime": ("time", "设置指定时钟源的时间"),
    "clock_getres":  ("time", "获取指定时钟源的精度"),
    "gettimeofday":  ("time", "获取系统时间"),
    "settimeofday":  ("time", "设置系统时间"),
    "times":         ("time", "获取进程消耗的 CPU 时间"),
    "timer_create":  ("time", "创建 POSIX 定时器"),
    "timer_settime": ("time", "设置 POSIX 定时器到期时间"),
    "timer_gettime": ("time", "查询 POSIX 定时器剩余时间"),
    "timer_delete":  ("time", "删除 POSIX 定时器"),
    "timerfd_create": ("time", "创建用 fd 表示的定时器"),

    # ===== 其他 =====
    "uname":         ("other", "获取操作系统名称、版本等信息"),
    "sysinfo":       ("other", "获取系统整体运行信息"),
    "syslog":        ("other", "读取或控制内核日志"),
    "reboot":        ("other", "重启或关机"),
    "getrandom":     ("other", "获取高质量随机字节"),
    "prctl":         ("other", "对调用进程进行各种控制操作"),
    "arch_prctl":    ("other", "架构相关的 prctl"),
}

# 关键字猜分类（命中字典外的 fallback）
_KW_HINTS: list[tuple[tuple[str, ...], SyscallCategory]] = [
    (("mmap", "munmap", "mprotect", "brk", "shm"), "memory"),
    (("fork", "exec", "exit", "wait", "clone", "pid", "uid", "gid",
      "sched", "tid", "tgid", "pgid", "kill", "robust"), "process"),
    (("futex", "sem", "mutex", "lock"), "sync"),
    (("sig",), "signal"),
    (("socket", "bind", "listen", "accept", "connect", "send", "recv",
      "sockopt", "tcp", "udp"), "net"),
    (("clock", "time", "sleep", "timer"), "time"),
    (("read", "write", "open", "close", "stat", "dir", "file",
      "fs", "mount", "dup", "pipe", "fd", "ioctl", "fcntl",
      "link", "chown", "chmod", "access", "sync", "poll", "select",
      "epoll", "sendfile", "splice"), "file"),
]


def _normalize(name: str) -> str:
    """统一处理 sys_/syscall_id_/__NR_ 前缀，转小写。"""
    n = name.strip().lower()
    for prefix in ("syscall_id_", "syscall_", "sys_", "__nr_", "nr_"):
        if n.startswith(prefix):
            n = n[len(prefix):]
            break
    for suffix in ("_internal", "_impl"):
        if n.endswith(suffix):
            n = n[: -len(suffix)]
    return n


def classify(name: str) -> tuple[SyscallCategory, str]:
    """返回 (category, description)。未命中字典时尝试关键字猜分类，description=''。"""
    norm = _normalize(name)
    hit = _SYSCALL_DICT.get(norm)
    if hit is not None:
        return hit
    for kws, cat in _KW_HINTS:
        if any(kw in norm for kw in kws):
            return cat, ""
    return "other", ""


# 中文分类名（用于报告渲染）
CATEGORY_LABEL_ZH: dict[str, str] = {
    "process": "进程相关",
    "file":    "文件操作相关",
    "memory":  "内存管理相关",
    "sync":    "同步相关",
    "signal":  "信号相关",
    "net":     "网络相关",
    "time":    "时间相关",
    "other":   "其他系统调用",
}

CATEGORY_ORDER: list[SyscallCategory] = [
    "process", "file", "memory", "sync", "signal", "net", "time", "other",
]
