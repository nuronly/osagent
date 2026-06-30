"""L3 StructuralSignature：跨仓库结构签名（用于查重）。

v1 实现：基于"源文件路径 + 文件大小桶"和"函数名集合"的 MinHash 签名。
精度不高，但对"同源衍生"识别已经够用；v2 升级为基于调用图的签名。

注：依赖 datasketch 库（可选）。如果没装，本模块退化为返回空签名。
"""
from __future__ import annotations

import hashlib

from ..logging import logger
from ..schemas import CallGraph
from .core import ScanResult

NUM_PERM = 128


def _try_import_minhash():
    try:
        from datasketch import MinHash  # type: ignore
        return MinHash
    except ImportError:
        logger.debug("datasketch 未安装，L3 跳过；如需查重请 pip install datasketch")
        return None


def run(scan: ScanResult, cg: CallGraph) -> list[int] | None:
    """返回 MinHash 签名（int 数组）；不可用返回 None。"""
    MinHash = _try_import_minhash()
    if MinHash is None:
        return None

    mh = MinHash(num_perm=NUM_PERM)

    # 1) 源文件路径（按目录前两段，规避命名差异）
    for f in scan.files:
        if not f.is_source:
            continue
        parts = f.rel.split("/")
        key = "/".join(parts[:2]) + ":" + str(f.size // 1024)
        mh.update(key.encode("utf-8"))

    # 2) 函数名集合（去掉路径）
    for node in cg.nodes:
        name = node.qualified_name.rsplit(":", 1)[-1]
        if len(name) >= 4:
            mh.update(name.encode("utf-8"))

    return [int(x) for x in mh.hashvalues]


def jaccard(sig_a: list[int] | None, sig_b: list[int] | None) -> float:
    """对两个签名估算 Jaccard 相似度。"""
    if not sig_a or not sig_b or len(sig_a) != len(sig_b):
        return 0.0
    eq = sum(1 for a, b in zip(sig_a, sig_b) if a == b)
    return eq / len(sig_a)
