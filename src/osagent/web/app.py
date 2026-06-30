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
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from ..analyzer import (
    analyze_by_repo_id,
    facts_path,
    get_manager,
    has_facts,
    load_facts,
)
from ..report import (
    build_compare_report,
    build_report,
    compare_html_path,
    compare_json_path,
    compare_md_path,
    has_compare_html,
    has_compare_json,
    has_compare_md,
    has_html,
    has_md,
    html_path,
    md_path,
)
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
from ..qa import ask as qa_ask
from ..qa.retriever import retrieve as qa_retrieve
from ..schemas import RepoStatus
from ..schemas.qa import QARequest

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

    # ---------- 静态分析（异步） ----------

    @app.post("/api/repos/{repo_id}/analyze")
    def api_repo_analyze(
        repo_id: str,
        level: str = "L2",
        force: bool = False,
        budget: float = 30.0,
    ) -> dict[str, Any]:
        """提交一个分析任务到 JobManager，立刻返回 job_id。前端再轮询进度。"""
        if level not in {"L1", "L2", "L3"}:
            raise HTTPException(400, f"level 必须是 L1/L2/L3，得到: {level}")

        # 已存在且不强制 → 不开 job
        if has_facts(repo_id) and not force:
            return {
                "ok": True,
                "cached": True,
                "repo_id": repo_id,
                "facts_path": str(facts_path(repo_id)),
            }

        m = load_manifest()
        entry = next((r for r in m.repos if r.repo_id == repo_id), None)
        if not entry:
            raise HTTPException(404, f"repo_id 未找到: {repo_id}")
        if not entry.local_path:
            raise HTTPException(
                400, f"repo {repo_id} 尚未克隆（status={entry.status.value}），请先 clone"
            )

        mgr = get_manager()

        def _run(job, cb):  # noqa: ANN001
            facts = analyze_by_repo_id(
                repo_id,
                level=level,  # type: ignore[arg-type]
                on_progress=cb,
                l2_budget_seconds=budget,
            )
            return {
                "repo_id": facts.repo_id,
                "summary": facts.summary_for_embedding,
                "facts_path": str(facts_path(facts.repo_id)),
            }

        job_id = mgr.submit(
            kind="analyze",
            payload={"repo_id": repo_id, "level": level, "budget": budget, "force": force},
            fn=_run,
        )
        return {"ok": True, "cached": False, "job_id": job_id, "repo_id": repo_id}

    @app.get("/api/jobs/{job_id}")
    def api_job_status(job_id: str) -> dict[str, Any]:
        job = get_manager().get(job_id)
        if job is None:
            raise HTTPException(404, f"job 未找到: {job_id}")
        d = job.to_dict()
        if job.status == "done":
            d["result"] = job.result
        return d

    @app.get("/api/jobs")
    def api_job_list(limit: int = 30) -> dict[str, Any]:
        jobs = get_manager().list_recent(limit=limit)
        return {"items": [j.to_dict() for j in jobs]}

    # ---------- 事实表查询 ----------

    @app.get("/api/repos/{repo_id}/facts")
    def api_repo_facts(repo_id: str) -> dict[str, Any]:
        if not has_facts(repo_id):
            raise HTTPException(
                404,
                f"事实表不存在，请先 POST /api/repos/{repo_id}/analyze",
            )
        f = load_facts(repo_id)
        return f.model_dump(mode="json")

    @app.get("/api/repos/{repo_id}/facts/summary")
    def api_repo_facts_summary(repo_id: str) -> dict[str, Any]:
        """轻量摘要：避免一次拉整张表（前端列表用）。"""
        if not has_facts(repo_id):
            raise HTTPException(404, "facts 未生成")
        f = load_facts(repo_id)
        return {
            "repo_id": f.repo_id,
            "extracted_at": f.extracted_at.isoformat(),
            "head_commit": f.head_commit,
            "languages": [s.model_dump() for s in f.basics.languages[:5]],
            "total_loc": f.basics.total_loc,
            "arch": f.basics.arch,
            "build": f.basics.build.kind,
            "base_template": f.basics.base_template,
            "subsystems": sorted({kf.feature for kf in f.kernel_features}),
            "syscall_count": f.syscalls.count,
            "function_node_count": len(f.call_graph.nodes),
            "dev_history": {
                "commits": f.dev_history.commits_total,
                "contributors": f.dev_history.contributors_total,
                "first": f.dev_history.first_commit_at.isoformat() if f.dev_history.first_commit_at else None,
                "last": f.dev_history.last_commit_at.isoformat() if f.dev_history.last_commit_at else None,
            },
            "summary": f.summary_for_embedding,
        }

    # ---------- 报告 ----------

    @app.post("/api/repos/{repo_id}/report")
    def api_repo_report(
        repo_id: str,
        fmt: str = "both",
    ) -> dict[str, Any]:
        """生成单仓库分析报告。需要事实表已存在（先 POST /analyze）。

        Returns: {"ok", "md_path"?, "html_path"?, "md_chars"?, "html_chars"?}
        """
        if fmt not in {"md", "html", "both"}:
            raise HTTPException(400, f"fmt 必须是 md/html/both，得到: {fmt}")
        if not has_facts(repo_id):
            raise HTTPException(
                400, f"事实表不存在，请先 POST /api/repos/{repo_id}/analyze",
            )
        try:
            out = build_report(repo_id, fmt=fmt)  # type: ignore[arg-type]
        except Exception as e:
            logger.exception("build_report 失败")
            raise HTTPException(500, str(e))
        return {"ok": True, **out}

    @app.get("/api/repos/{repo_id}/report.md", response_class=PlainTextResponse)
    def api_repo_report_md(repo_id: str) -> PlainTextResponse:
        if not has_md(repo_id):
            raise HTTPException(
                404, f"Markdown 报告不存在，先 POST /api/repos/{repo_id}/report",
            )
        return PlainTextResponse(
            md_path(repo_id).read_text(encoding="utf-8"),
            media_type="text/markdown; charset=utf-8",
        )

    @app.get("/api/repos/{repo_id}/report.html", response_class=HTMLResponse)
    def api_repo_report_html(repo_id: str) -> HTMLResponse:
        if not has_html(repo_id):
            raise HTTPException(
                404, f"HTML 报告不存在，先 POST /api/repos/{repo_id}/report",
            )
        return HTMLResponse(html_path(repo_id).read_text(encoding="utf-8"))

    @app.get("/api/repos/{repo_id}/report/status")
    def api_repo_report_status(repo_id: str) -> dict[str, Any]:
        return {
            "repo_id": repo_id,
            "has_facts": has_facts(repo_id),
            "has_md": has_md(repo_id),
            "has_html": has_html(repo_id),
        }

    # ---------- 两仓库对比 ----------

    @app.post("/api/compare")
    def api_compare_build(
        a: str = Query(..., description="A 仓库 ID"),
        b: str = Query(..., description="B 仓库 ID"),
        fmt: str = "both",
    ) -> dict[str, Any]:
        """生成两仓库对比报告（md + html + json）。"""
        if fmt not in {"md", "html", "both"}:
            raise HTTPException(400, f"fmt 必须是 md/html/both，得到: {fmt}")
        if a == b:
            raise HTTPException(400, "两个 repo_id 不能相同")
        for rid in (a, b):
            if not has_facts(rid):
                raise HTTPException(
                    400, f"事实表不存在: {rid}. 请先 POST /api/repos/{rid}/analyze"
                )
        try:
            out = build_compare_report(a, b, fmt=fmt)  # type: ignore[arg-type]
        except Exception as e:
            logger.exception("build_compare_report 失败")
            raise HTTPException(500, str(e))
        return {"ok": True, **out}

    @app.get("/api/compare/status")
    def api_compare_status(a: str = Query(...), b: str = Query(...)) -> dict[str, Any]:
        return {
            "a": a,
            "b": b,
            "has_facts_a": has_facts(a),
            "has_facts_b": has_facts(b),
            "has_md": has_compare_md(a, b),
            "has_html": has_compare_html(a, b),
            "has_json": has_compare_json(a, b),
        }

    @app.get("/api/compare.md", response_class=PlainTextResponse)
    def api_compare_md(a: str = Query(...), b: str = Query(...)) -> PlainTextResponse:
        if not has_compare_md(a, b):
            raise HTTPException(404, "Markdown 对比报告不存在，先 POST /api/compare")
        return PlainTextResponse(
            compare_md_path(a, b).read_text(encoding="utf-8"),
            media_type="text/markdown; charset=utf-8",
        )

    @app.get("/api/compare.html", response_class=HTMLResponse)
    def api_compare_html_api(a: str = Query(...), b: str = Query(...)) -> HTMLResponse:
        if not has_compare_html(a, b):
            raise HTTPException(404, "HTML 对比报告不存在，先 POST /api/compare")
        return HTMLResponse(compare_html_path(a, b).read_text(encoding="utf-8"))

    @app.get("/api/compare.json")
    def api_compare_json(a: str = Query(...), b: str = Query(...)) -> dict[str, Any]:
        """直接返回结构化 CompareReport（前端可直接渲染雷达图等）。"""
        if not has_compare_json(a, b):
            raise HTTPException(404, "JSON 对比报告不存在，先 POST /api/compare")
        import json as _json
        return _json.loads(compare_json_path(a, b).read_text(encoding="utf-8"))

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

    # ---------- QA（检索增强问答） ----------

    @app.post("/api/qa")
    def api_qa(req: QARequest) -> dict[str, Any]:
        """开放问答：scope=repo|compare|global。

        body 示例（repo）::

            {"question": "内存管理用了什么算法？", "scope": "repo",
             "repo_id": "2024_001_xxx"}

        body 示例（compare）::

            {"question": "ECNU 九队与 RuaruaOs 的 syscall 设计本质区别在哪？",
             "scope": "compare", "repo_id_a": "...", "repo_id_b": "..."}
        """
        try:
            resp = qa_ask(req)
        except Exception as e:
            logger.exception("QA 失败")
            raise HTTPException(500, f"QA 失败: {e}")
        return resp.model_dump(mode="json")

    @app.post("/api/qa/preview")
    def api_qa_preview(req: QARequest) -> dict[str, Any]:
        """只跑检索，不调 LLM。用于调试 / 节省 token。"""
        try:
            items, warns = qa_retrieve(req)
        except Exception as e:
            logger.exception("QA preview 失败")
            raise HTTPException(500, f"QA preview 失败: {e}")
        return {
            "ok": True,
            "items": [it.model_dump(mode="json") for it in items],
            "warnings": warns,
            "context_chars": sum(len(it.body) for it in items),
        }

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
