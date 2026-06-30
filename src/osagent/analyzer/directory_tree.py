"""目录树构建：从 ScanResult 生成一棵裁剪后的 DirectoryNode。

限制：
- 最大深度 MAX_DEPTH（默认 3）
- 总节点数 MAX_NODES（默认 200，超出按 file_count 降序裁剪）
- 子节点排序：dir 优先，同类按 (file_count desc, name asc)
- 文件节点带 loc（仅 source 类型）
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import PurePosixPath

from ..schemas import DirectoryNode
from .core import ScanResult

MAX_DEPTH = 3
MAX_NODES = 200


def build_tree(scan: ScanResult, *, max_depth: int = MAX_DEPTH, max_nodes: int = MAX_NODES) -> DirectoryNode:
    """生成目录树。

    实现：
    1) 第一遍：把所有 file 按"祖先路径深度截断到 max_depth"重新归类，
       这样深处的文件会被卷起到第 max_depth 层目录的"file_count"。
    2) 第二遍：实际只生成 max_depth+1 层节点（根=0 层）。
    3) 第三遍：裁剪，每个目录的子节点超过阈值时按 file_count 降序保留。
    """
    # 全部文件相对路径
    files_info: list[tuple[PurePosixPath, int]] = []  # (rel_path, loc)
    for f in scan.files:
        files_info.append((PurePosixPath(f.rel), _loc_of(f)))

    root = DirectoryNode(name=scan.root.name, path="", kind="dir", loc=0, file_count=0)
    if not files_info:
        return root

    # 构建临时树
    # node_index: path_str -> DirectoryNode
    node_index: dict[str, DirectoryNode] = {"": root}

    for rel, loc in files_info:
        parts = rel.parts
        # 累计到根
        root.file_count += 1
        root.loc += loc

        depth = min(len(parts) - 1, max_depth)
        # 创建沿途的目录节点（最多到 depth 层）
        cur_path = ""
        for i in range(depth):
            seg = parts[i]
            cur_path = f"{cur_path}/{seg}" if cur_path else seg
            node = node_index.get(cur_path)
            if node is None:
                parent_path = "/".join(parts[:i]) if i > 0 else ""
                parent = node_index[parent_path]
                node = DirectoryNode(
                    name=seg, path=cur_path, kind="dir", loc=0, file_count=0
                )
                parent.children.append(node)
                node_index[cur_path] = node
            node.file_count += 1
            node.loc += loc

        # 叶节点处理
        if len(parts) - 1 <= max_depth:
            # 文件原位
            file_name = parts[-1]
            file_path = "/".join(parts)
            parent_path = "/".join(parts[:-1]) if len(parts) > 1 else ""
            parent = node_index[parent_path]
            parent.children.append(
                DirectoryNode(
                    name=file_name, path=file_path, kind="file", loc=loc, file_count=1
                )
            )
        # 否则：文件被卷入到第 max_depth 层目录，不创建叶子（避免节点爆炸）

    # 排序 + 裁剪
    _sort_and_prune(root, max_nodes)
    return root


def _loc_of(file_item) -> int:  # noqa: ANN001
    """估算单文件 loc：源码取 size/40 的粗估，非源码取 0。
    
    注意：精确 loc 需要真读文件，这里用 size 估算避免二次 IO。
    """
    if not file_item.is_source:
        return 0
    # 经验：源代码平均行长约 30-50 字节
    return max(1, file_item.size // 40)


def _sort_and_prune(node: DirectoryNode, max_nodes: int) -> None:
    """递归排序 children，并在总节点数超限时裁剪。
    
    排序规则：dir 优先，再按 file_count 降序，再按 name 升序。
    """
    if not node.children:
        return
    # 先递归
    for c in node.children:
        if c.kind == "dir":
            _sort_and_prune(c, max_nodes)
    # 排序
    node.children.sort(key=lambda x: (0 if x.kind == "dir" else 1, -x.file_count, x.name))

    # 全局节点数计算
    total = _count_nodes(node)
    if total <= max_nodes:
        return

    # 简单裁剪策略：自上而下每个目录最多保留 K 个子节点
    # K 从 12 起，逐步递减直到满足
    k = 12
    while k >= 4 and _count_nodes(node) > max_nodes:
        _truncate_children(node, k)
        k -= 2


def _count_nodes(node: DirectoryNode) -> int:
    return 1 + sum(_count_nodes(c) for c in node.children)


def _truncate_children(node: DirectoryNode, k: int) -> None:
    if len(node.children) > k:
        node.children = node.children[:k]
    for c in node.children:
        if c.kind == "dir":
            _truncate_children(c, k)


def render_ascii(node: DirectoryNode) -> str:
    """渲染目录树为 ASCII 文本（用于报告中插入 ```text``` 段）。"""
    lines: list[str] = [f"{node.name}/"]
    _render_children(node, prefix="", lines=lines)
    return "\n".join(lines)


def _render_children(node: DirectoryNode, *, prefix: str, lines: list[str]) -> None:
    children = node.children
    n = len(children)
    for idx, child in enumerate(children):
        is_last = idx == n - 1
        connector = "└── " if is_last else "├── "
        suffix = "/" if child.kind == "dir" else ""
        lines.append(f"{prefix}{connector}{child.name}{suffix}")
        if child.kind == "dir" and child.children:
            new_prefix = prefix + ("    " if is_last else "│   ")
            _render_children(child, prefix=new_prefix, lines=lines)
