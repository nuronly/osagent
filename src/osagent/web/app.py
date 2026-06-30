"""FastAPI Web 服务：极简仪表盘 + REST API。

设计目标：让用户用浏览器看到 manifest 全貌、跑 ping、看仓库详情。
不引入前端构建工具，纯静态 HTML/JS，方便用户后续自由扩展。
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from ..config import settings
from ..ingest import (
    build_manifest,
    clone_one,
    load_manifest,
    manifest_stats,
    save_manifest,
)
from ..llm import get_client
from ..logging import logger
from ..schemas import RepoStatus

STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    app = FastAPI(
        title="osAgent",
        description="面向小型操作系统的分析比对智能体系统 — 仪表盘 API",
        version="0.1.0",
    )

    # ---------- Manifest ----------

    @app.get("/api/manifest/stats")
    def api_manifest_stats() -> dict[str, Any]:
        """全局概览：年份、host、状态、track 分布。"""
        try:
            m = load_manifest()
        except FileNotFoundError as e:
            raise HTTPException(404, str(e))
        return {
            "version": m.version,
            "generated_at": m.generated_at.isoformat(),
            "source_xlsx": m.source_xlsx,
            **manifest_stats(m),
        }

    @app.get("/api/manifest/repos")
    def api_manifest_repos(
        year: int | None = Query(None, ge=2021, le=2030),
        status: str | None = Query(None),
        school: str | None = Query(None),
        q: str | None = Query(None, description="搜索 team / school / repo_id"),
        page: int = Query(1, ge=1),
        page_size: int = Query(30, ge=1, le=500),
    ) -> dict[str, Any]:
        """分页 + 过滤的仓库列表。"""
        try:
            m = load_manifest()
        except FileNotFoundError as e:
            raise HTTPException(404, str(e))

        repos = m.repos
        if year:
            repos = [r for r in repos if r.year == year]
        if status:
            repos = [r for r in repos if r.status.value == status]
        if school:
            repos = [r for r in repos if school in r.school]
        if q:
            ql = q.lower()
            repos = [
                r for r in repos
                if ql in r.team.lower()
                or ql in r.school.lower()
                or ql in r.repo_id.lower()
            ]

        total = len(repos)
        start = (page - 1) * page_size
        end = start + page_size
        items = [r.model_dump(mode="json") for r in repos[start:end]]
        return {"total": total, "page": page, "page_size": page_size, "items": items}

    @app.get("/api/manifest/repos/{repo_id}")
    def api_repo_detail(repo_id: str) -> dict[str, Any]:
        m = load_manifest()
        entry = next((r for r in m.repos if r.repo_id == repo_id), None)
        if not entry:
            raise HTTPException(404, f"repo_id 未找到: {repo_id}")
        data = entry.model_dump(mode="json")
        # 附加：本地是否真实存在
        if entry.local_path:
            p = Path(entry.local_path)
            data["local_exists"] = p.exists()
        return data

    @app.post("/api/manifest/build")
    def api_manifest_build() -> dict[str, Any]:
        """重建 manifest（从 collected-data.xlsx）。"""
        m = build_manifest()
        return {"ok": True, "total": m.total}

    # ---------- 单仓库拉取（同步，阻塞调用方；适合调试） ----------

    @app.post("/api/repos/{repo_id}/clone")
    def api_repo_clone(repo_id: str, depth: int = 1, force: bool = False) -> dict[str, Any]:
        m = load_manifest()
        entry = next((r for r in m.repos if r.repo_id == repo_id), None)
        if not entry:
            raise HTTPException(404, f"repo_id 未找到: {repo_id}")
        clone_one(entry, force=force, depth=depth)
        save_manifest(m)
        return entry.model_dump(mode="json")

    # ---------- LLM ----------

    @app.get("/api/llm/ping")
    def api_llm_ping() -> dict[str, Any]:
        try:
            return {"ok": True, **get_client().ping()}
        except Exception as e:
            logger.exception("ping 失败")
            return JSONResponse(
                status_code=500,
                content={"ok": False, "error": str(e)},
            )

    # ---------- 演进大盘（先做一个最简单的：按年份的仓库数 + 状态） ----------

    @app.get("/api/dashboard/yearly")
    def api_dashboard_yearly() -> dict[str, Any]:
        """简易演进大盘：按年份的总数、已克隆数、平均文件数 / 平均大小。

        注：W3 之后会加入语言占比、特性渗透率等。
        """
        m = load_manifest()
        by_year: dict[int, dict[str, Any]] = {}
        for r in m.repos:
            d = by_year.setdefault(
                r.year,
                {"year": r.year, "total": 0, "ok": 0, "loc_files_sum": 0, "size_bytes_sum": 0},
            )
            d["total"] += 1
            if r.status == RepoStatus.OK:
                d["ok"] += 1
                d["loc_files_sum"] += r.file_count or 0
                d["size_bytes_sum"] += r.size_bytes or 0

        rows = []
        for d in sorted(by_year.values(), key=lambda x: x["year"]):
            ok = d["ok"]
            rows.append(
                {
                    "year": d["year"],
                    "total": d["total"],
                    "ok": ok,
                    "avg_files": round(d["loc_files_sum"] / ok, 1) if ok else 0,
                    "avg_size_kb": round(d["size_bytes_sum"] / ok / 1024, 1) if ok else 0,
                }
            )
        return {"rows": rows, "generated_at": datetime.now().isoformat()}

    # ---------- 健康检查 ----------

    @app.get("/api/health")
    def api_health() -> dict[str, Any]:
        return {
            "ok": True,
            "data_dir": str(settings.data_dir),
            "manifest_exists": settings.manifest_path.exists(),
        }

    # ---------- 静态前端 ----------

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()
