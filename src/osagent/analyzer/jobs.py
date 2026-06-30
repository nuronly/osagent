"""JobManager：内存级任务队列 + 进度跟踪 + 结果缓存。

适用场景：单进程 Web Server / CLI 共用。任务提交后立刻返回 job_id，
后台线程跑分析；前端轮询 progress 看进度，完成后取 result。

不引入 Celery / Redis，保持简单；后续如需多机扩展再替换实现。
"""
from __future__ import annotations

import threading
import traceback
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Literal

from ..logging import logger

JobStatus = Literal["queued", "running", "done", "error"]


@dataclass
class JobProgress:
    stage: str = ""
    msg: str = ""
    pct: int = 0
    updated_at: datetime = field(default_factory=datetime.now)


@dataclass
class Job:
    job_id: str
    kind: str                                # "analyze" / "compare" / ...
    payload: dict[str, Any]
    status: JobStatus = "queued"
    progress: JobProgress = field(default_factory=JobProgress)
    result: Any = None
    error: str | None = None
    created_at: datetime = field(default_factory=datetime.now)
    started_at: datetime | None = None
    finished_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "kind": self.kind,
            "payload": self.payload,
            "status": self.status,
            "progress": {
                "stage": self.progress.stage,
                "msg": self.progress.msg,
                "pct": self.progress.pct,
                "updated_at": self.progress.updated_at.isoformat(),
            },
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            # result 单独取（可能很大）
        }


class JobManager:
    """单例任务管理器。线程安全。"""

    def __init__(self, max_workers: int = 2, max_keep: int = 200) -> None:
        self._jobs: OrderedDict[str, Job] = OrderedDict()
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="job")
        self._max_keep = max_keep

    def submit(
        self,
        kind: str,
        payload: dict[str, Any],
        fn: Callable[[Job, Callable[[str, str, int], None]], Any],
    ) -> str:
        """提交一个任务，返回 job_id。

        fn 签名: (job, progress_callback) -> result
        progress_callback(stage, msg, pct) 由 fn 内部调用。
        """
        job = Job(job_id=uuid.uuid4().hex[:12], kind=kind, payload=payload)
        with self._lock:
            self._jobs[job.job_id] = job
            self._gc_locked()

        def _run() -> None:
            with self._lock:
                job.status = "running"
                job.started_at = datetime.now()

            def cb(stage: str, msg: str, pct: int) -> None:
                with self._lock:
                    job.progress = JobProgress(
                        stage=stage, msg=msg, pct=max(0, min(100, pct)),
                        updated_at=datetime.now(),
                    )
                logger.debug(f"[job {job.job_id}] {stage} {pct}% {msg}")

            try:
                result = fn(job, cb)
                with self._lock:
                    job.result = result
                    job.status = "done"
                    job.progress = JobProgress(
                        stage="done", msg="完成", pct=100, updated_at=datetime.now()
                    )
                    job.finished_at = datetime.now()
            except Exception as e:
                logger.exception(f"[job {job.job_id}] failed: {e}")
                with self._lock:
                    job.status = "error"
                    job.error = f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=5)}"
                    job.finished_at = datetime.now()

        self._pool.submit(_run)
        return job.job_id

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_recent(self, limit: int = 30) -> list[Job]:
        with self._lock:
            return list(self._jobs.values())[-limit:][::-1]

    def _gc_locked(self) -> None:
        """超过 max_keep 删除最旧的（必须在 lock 内调用）。"""
        while len(self._jobs) > self._max_keep:
            self._jobs.popitem(last=False)


# 单例
_manager: JobManager | None = None


def get_manager() -> JobManager:
    global _manager
    if _manager is None:
        _manager = JobManager()
    return _manager
