"""仓库克隆：批量 / 抽样，状态写回 manifest。

设计要点：
- 用子进程跑 `git clone`，强制超时（避免长尾仓库卡死）；
- 并发用线程池（git 本身是 IO 密集）；
- 每个仓库完成后立刻回写 manifest（崩溃可续跑）；
- 已存在的仓库默认跳过；可用 force=True 强制重拉。
"""
from __future__ import annotations

import os
import random
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from threading import Lock

from ..config import settings
from ..logging import logger
from ..schemas import Manifest, RepoEntry, RepoStatus
from .manifest import save_manifest


_save_lock = Lock()


def _local_path_for(entry: RepoEntry) -> Path:
    return settings.repos_dir / str(entry.year) / entry.repo_id


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 120) -> tuple[int, str]:
    """运行子进程，返回 (returncode, combined_output)。"""
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except subprocess.TimeoutExpired as e:
        return 124, f"TIMEOUT after {timeout}s: {e}"
    except Exception as e:
        return 1, f"EXCEPTION: {e!r}"


def _dir_stats(path: Path) -> tuple[int, int]:
    """返回 (size_bytes, file_count)，跳过 .git。"""
    total_size = 0
    total_files = 0
    for root, dirs, files in os.walk(path):
        if ".git" in dirs:
            dirs.remove(".git")
        for f in files:
            fp = Path(root) / f
            try:
                total_size += fp.stat().st_size
                total_files += 1
            except OSError:
                pass
    return total_size, total_files


def _git_meta(repo_path: Path) -> tuple[str | None, str | None]:
    """返回 (default_branch, head_commit)。"""
    rc, out = _run(["git", "rev-parse", "HEAD"], cwd=repo_path, timeout=10)
    head = out.strip() if rc == 0 else None

    rc, out = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path, timeout=10)
    branch = out.strip() if rc == 0 else None
    return branch, head


def clone_one(entry: RepoEntry, *, force: bool = False, depth: int | None = None) -> RepoEntry:
    """克隆单个仓库；返回更新后的 entry（不写盘，由调用方统一保存）。"""
    target = _local_path_for(entry)
    entry.local_path = str(target)

    if target.exists() and not force:
        if (target / ".git").exists():
            branch, head = _git_meta(target)
            size, files = _dir_stats(target)
            entry.status = RepoStatus.OK
            entry.default_branch = branch
            entry.head_commit = head
            entry.size_bytes = size
            entry.file_count = files
            entry.cloned_at = entry.cloned_at or datetime.now()
            logger.debug(f"[skip] {entry.repo_id} 已存在")
            return entry
        else:
            shutil.rmtree(target, ignore_errors=True)

    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)

    depth = depth if depth is not None else settings.git_clone_depth
    cmd = ["git", "clone", "--quiet"]
    if depth and depth > 0:
        cmd += ["--depth", str(depth)]
    cmd += [entry.repo_url, str(target)]

    logger.info(f"[clone] {entry.repo_id}  <- {entry.repo_url}")
    rc, out = _run(cmd, timeout=settings.git_clone_timeout)

    if rc == 0 and target.exists():
        branch, head = _git_meta(target)
        size, files = _dir_stats(target)
        entry.status = RepoStatus.OK
        entry.default_branch = branch
        entry.head_commit = head
        entry.size_bytes = size
        entry.file_count = files
        entry.cloned_at = datetime.now()
        entry.error_msg = None
        logger.success(
            f"[ok]   {entry.repo_id}  files={files}  size={size/1024:.0f}KB  head={head[:8] if head else 'N/A'}"
        )
    else:
        if rc == 124:
            entry.status = RepoStatus.TIMEOUT
        else:
            # 简单判定：链接失效 / 不存在 / 私有
            err_lower = out.lower()
            if any(k in err_lower for k in [
                "not found", "does not exist", "could not resolve",
                "repository not found", "404", "authentication failed",
                "permission denied",
            ]):
                entry.status = RepoStatus.UNREACHABLE
            else:
                entry.status = RepoStatus.ERROR
        entry.error_msg = out.strip()[-500:]
        logger.warning(f"[fail] {entry.repo_id}  status={entry.status.value}")

    return entry


def clone_many(
    manifest: Manifest,
    entries: list[RepoEntry] | None = None,
    *,
    force: bool = False,
    concurrency: int | None = None,
    depth: int | None = None,
    save_every: int = 5,
) -> Manifest:
    """并发克隆多个仓库；每完成 save_every 个就把 manifest 落盘一次。"""
    todo = entries if entries is not None else manifest.repos
    if not todo:
        logger.warning("没有要克隆的仓库")
        return manifest

    concurrency = concurrency or settings.git_concurrency
    logger.info(f"开始克隆: {len(todo)} 个仓库, 并发={concurrency}, force={force}, depth={depth}")

    done = 0
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = {pool.submit(clone_one, e, force=force, depth=depth): e for e in todo}
        for fut in as_completed(futures):
            try:
                fut.result()
            except Exception as exc:
                e = futures[fut]
                e.status = RepoStatus.ERROR
                e.error_msg = repr(exc)
                logger.exception(f"克隆异常: {e.repo_id}")

            done += 1
            if done % save_every == 0:
                with _save_lock:
                    save_manifest(manifest)
                logger.info(f"进度 {done}/{len(todo)}  manifest 已落盘")

    with _save_lock:
        save_manifest(manifest)
    logger.success(f"克隆完成: {done}/{len(todo)}")
    return manifest


def sample_probe(
    manifest: Manifest,
    n: int = 5,
    *,
    seed: int = 42,
    depth: int = 1,
) -> list[RepoEntry]:
    """随机抽 n 个仓库做连通性探测（默认浅克隆，省流量）。"""
    rng = random.Random(seed)
    sample = rng.sample(manifest.repos, k=min(n, len(manifest.repos)))
    logger.info(f"抽样 {len(sample)} 个仓库做连通性探测 (depth={depth})")
    clone_many(manifest, entries=sample, force=True, concurrency=min(4, n), depth=depth)
    return sample
