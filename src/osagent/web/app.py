"""FastAPI Web 服务：极简仪表盘 + REST API。

设计目标：让用户用浏览器看到 manifest 全貌、跑 ping、看仓库详情。
不引入前端构建工具，纯静态 HTML/JS，方便用户后续自由扩展。
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import tempfile

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
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
    add_repo_manual,
    build_manifest,
    clone_one,
    delete_repo,
    import_xlsx_incremental,
    load_manifest,
    manifest_stats,
    save_manifest,
)
from ..llm import get_client
from ..logging import logger
from ..qa import ask as qa_ask
from ..qa.retriever import retrieve as qa_retrieve
from ..schemas import ManualRepoInput, RepoStatus
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

    @app.get("/api/manifest/years")
    def api_manifest_years() -> dict[str, Any]:
        """返回 manifest 中出现过的所有年份（升序），供前端 dropdown 用。"""
        try:
            m = load_manifest()
        except FileNotFoundError as e:
            raise HTTPException(404, str(e))
        years = sorted({r.year for r in m.repos})
        return {"years": years}

    @app.post("/api/manifest/import-xlsx")
    async def api_manifest_import_xlsx(
        file: UploadFile = File(..., description="包含 7 列（年份/赛事/子赛事/学校/队伍/仓库地址）的 .xlsx"),
        dry_run: bool = Form(False, description="True=只预览不写盘"),
    ) -> dict[str, Any]:
        """增量导入 Excel（merge 策略：URL 已存在则跳过，不动旧仓 repo_id）。

        - dry_run=True 返回完整 ImportReport 供前端预览，再让用户确认
        - dry_run=False 实际写盘，并自动备份当前 manifest 到 data/backups/
        """
        if not file.filename or not file.filename.lower().endswith((".xlsx", ".xls")):
            raise HTTPException(400, "请上传 .xlsx 文件")

        # 落到临时文件再走 openpyxl
        suffix = Path(file.filename).suffix or ".xlsx"
        try:
            content = await file.read()
        except Exception as e:
            raise HTTPException(400, f"读取上传文件失败: {e}")

        if not content:
            raise HTTPException(400, "上传文件为空")

        # 防止恶意巨型文件（10MB 上限，对 168 行的 xlsx 而言绰绰有余）
        if len(content) > 10 * 1024 * 1024:
            raise HTTPException(413, "文件过大（限制 10MB）")

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        try:
            tmp.write(content)
            tmp.flush()
            tmp.close()
            try:
                report = import_xlsx_incremental(
                    Path(tmp.name),
                    dry_run=dry_run,
                    source_label=file.filename,
                )
            except Exception as e:
                logger.exception("import_xlsx_incremental 失败")
                raise HTTPException(500, f"导入失败: {e}")
        finally:
            Path(tmp.name).unlink(missing_ok=True)

        return {"ok": True, "report": report.model_dump(mode="json")}

    @app.post("/api/manifest/add-repo")
    def api_manifest_add_repo(input_data: ManualRepoInput) -> dict[str, Any]:
        """手工添加一条仓库。URL 已存在则 409。"""
        try:
            entry = add_repo_manual(input_data)
        except ValueError as e:
            raise HTTPException(409, str(e))
        except Exception as e:
            logger.exception("add_repo_manual 失败")
            raise HTTPException(500, str(e))
        return {"ok": True, "entry": entry.model_dump(mode="json")}

    @app.delete("/api/manifest/repos/{repo_id}")
    def api_manifest_delete_repo(
        repo_id: str,
        purge_data: bool = Query(
            False,
            description="True=同时清理 data/repos/<id>、facts/<id>.json、reports/<id>.{md,html}",
        ),
    ) -> dict[str, Any]:
        """删除一条 manifest 记录。会自动备份当前 manifest。"""
        try:
            result = delete_repo(repo_id, purge_data=purge_data)
        except FileNotFoundError as e:
            raise HTTPException(404, str(e))
        except ValueError as e:
            raise HTTPException(404, str(e))
        except Exception as e:
            logger.exception("delete_repo 失败")
            raise HTTPException(500, str(e))
        return {"ok": True, "result": result.model_dump(mode="json")}

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

    @app.get("/report", response_class=HTMLResponse)
    def page_report(repo_id: str) -> HTMLResponse:
        """独立报告页面（v0.7.2）。

        新标签页打开，撑满浏览器宽度，左侧 sticky TOC + 右侧报告正文。
        数据源：
          - manifest entry → 头部学校/队伍/year/repo_url
          - facts summary  → 顶部 4 张数字摘要卡
          - reports/<id>.html → 抽出 <div class="container"> 正文，并扫 h2/h3 生成 TOC
        """
        # 1. 友好错误页
        if not has_facts(repo_id):
            return HTMLResponse(_render_report_error(
                repo_id, "事实表未生成", "请先在仪表盘点'抽取事实'生成 facts，再点'生成报告'。"
            ), status_code=404)
        if not has_html(repo_id):
            return HTMLResponse(_render_report_error(
                repo_id, "HTML 报告未生成", "请回仪表盘点'📄 生成报告'按钮后再访问。"
            ), status_code=404)

        # 2. manifest entry（meta 头部用）
        m = load_manifest()
        entry = next((r for r in m.repos if r.repo_id == repo_id), None)

        # 3. facts summary（顶部 4 张数字卡用）
        facts = load_facts(repo_id)
        summary_cards = _build_summary_cards(facts)

        # 4. 读 reports HTML 并抽出正文 + TOC
        raw_html = html_path(repo_id).read_text(encoding="utf-8")
        body_html, toc = _extract_body_and_toc(raw_html)

        # 5. 渲染模板
        template = (STATIC_DIR / "report.html").read_text(encoding="utf-8")
        return HTMLResponse(_fill_report_template(
            template,
            repo_id=repo_id,
            entry=entry,
            summary_cards=summary_cards,
            toc=toc,
            body_html=body_html,
        ))

    return app


# ============================================================
# 独立报告页面（v0.7.2）的辅助函数
# ============================================================

def _esc(s: Any) -> str:
    """HTML 转义。"""
    import html as _h
    return _h.escape("" if s is None else str(s))


def _fmt_bytes(n: int | None) -> str:
    if not n:
        return "-"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f}{unit}" if unit != "B" else f"{n}B"
        n = n / 1024  # type: ignore[assignment]
    return f"{n:.1f}TB"


def _fmt_num(n: Any) -> str:
    if n is None:
        return "-"
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return str(n)


def _build_summary_cards(facts) -> list[dict[str, str]]:  # noqa: ANN001
    """从 facts 提炼 4 张数字摘要卡（首屏给老师看的"硬指标"）。"""
    top_lang = facts.basics.languages[0].language if facts.basics.languages else "-"
    subsystems = sorted({kf.feature for kf in facts.kernel_features})
    return [
        {
            "label": "代码规模",
            "value": _fmt_num(facts.basics.total_loc),
            "unit": "LOC",
            "hint": f"主语言 {top_lang}",
        },
        {
            "label": "子系统",
            "value": str(len(subsystems)),
            "unit": "个",
            "hint": "、".join(subsystems[:3]) if subsystems else "-",
        },
        {
            "label": "syscalls",
            "value": _fmt_num(facts.syscalls.count),
            "unit": "个",
            "hint": f"调用图节点 {len(facts.call_graph.nodes)}",
        },
        {
            "label": "提交记录",
            "value": _fmt_num(facts.dev_history.commits_total),
            "unit": "commits",
            "hint": f"{facts.dev_history.contributors_total} 位贡献者",
        },
    ]


def _extract_body_and_toc(raw_html: str) -> tuple[str, list[dict[str, str]]]:
    """从 report.html 中抽出 <div class="container"> 正文 + h2/h3 列表。

    使用 stdlib html.parser，零新依赖。
    返回 (body_html, [{"level": "2|3", "id": "anchor", "text": "标题"}, ...])
    """
    from html.parser import HTMLParser

    class _Extractor(HTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=False)
            self.depth = 0
            self.in_container = False
            self.container_depth = 0
            self.body_parts: list[str] = []
            self.toc: list[dict[str, str]] = []
            self._capture_heading: str | None = None  # "2"|"3"
            self._heading_text: list[str] = []
            self._heading_id: str = ""
            self._auto_id_seed = 0

        def _attrs_to_str(self, attrs: list[tuple[str, str | None]]) -> str:
            parts = []
            for k, v in attrs:
                if v is None:
                    parts.append(k)
                else:
                    parts.append(f'{k}="{_esc(v)}"')
            return (" " + " ".join(parts)) if parts else ""

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            self.depth += 1
            attrs_dict = dict(attrs)
            if not self.in_container:
                if tag == "div" and "container" in (attrs_dict.get("class") or ""):
                    self.in_container = True
                    self.container_depth = self.depth
                return
            # 跳过 footer
            if tag == "footer":
                self._skip_footer = True  # type: ignore[attr-defined]
            if tag in ("h2", "h3"):
                self._capture_heading = tag[1]
                self._heading_text = []
                # 给标题强行加 id（若已有用已有的）
                hid = attrs_dict.get("id")
                if not hid:
                    self._auto_id_seed += 1
                    hid = f"toc-{self._auto_id_seed}"
                    attrs = list(attrs) + [("id", hid)]
                self._heading_id = hid
            self.body_parts.append(f"<{tag}{self._attrs_to_str(attrs)}>")

        def handle_endtag(self, tag: str) -> None:
            if self.in_container and self.depth == self.container_depth and tag == "div":
                self.in_container = False
                self.depth -= 1
                return
            if self.in_container:
                self.body_parts.append(f"</{tag}>")
                if self._capture_heading and tag == f"h{self._capture_heading}":
                    self.toc.append({
                        "level": self._capture_heading,
                        "id": self._heading_id,
                        "text": "".join(self._heading_text).strip(),
                    })
                    self._capture_heading = None
            self.depth -= 1

        def handle_data(self, data: str) -> None:
            if self.in_container:
                self.body_parts.append(data)
                if self._capture_heading:
                    self._heading_text.append(data)

        def handle_entityref(self, name: str) -> None:
            if self.in_container:
                self.body_parts.append(f"&{name};")

        def handle_charref(self, name: str) -> None:
            if self.in_container:
                self.body_parts.append(f"&#{name};")

    p = _Extractor()
    p.feed(raw_html)
    body = "".join(p.body_parts).strip()
    # 去掉尾部的 <footer>...</footer> ——后端生成的 HTML 末尾有"由 osAgent 生成"那段
    import re as _re
    body = _re.sub(r"<footer\b[^>]*>.*?</footer>", "", body, flags=_re.S | _re.I)
    return body, p.toc


def _fill_report_template(
    template: str,
    *,
    repo_id: str,
    entry,  # noqa: ANN001  RepoEntry | None
    summary_cards: list[dict[str, str]],
    toc: list[dict[str, str]],
    body_html: str,
) -> str:
    """把变量灌进 report.html 模板字符串（用 {{ key }} 占位，规避 Python format 与 CSS 冲突）。"""
    team = (entry.team if entry else repo_id) or repo_id
    school = (entry.school if entry else "") or ""
    year = (entry.year if entry else "") or ""
    contest = (entry.contest if entry else "") or ""
    track = (entry.track if entry else "") or ""
    repo_url = (entry.repo_url if entry else "") or ""

    # 顶部 4 张数字卡
    cards_html = "".join([
        f'<div class="summary-card">'
        f'  <div class="card-label">{_esc(c["label"])}</div>'
        f'  <div class="card-value">{_esc(c["value"])}<span class="card-unit">{_esc(c["unit"])}</span></div>'
        f'  <div class="card-hint">{_esc(c["hint"])}</div>'
        f'</div>'
        for c in summary_cards
    ])

    # TOC 列表
    if toc:
        toc_html = "<ul>" + "".join([
            f'<li class="toc-lvl-{_esc(item["level"])}">'
            f'<a href="#{_esc(item["id"])}">{_esc(item["text"])}</a>'
            f'</li>'
            for item in toc
        ]) + "</ul>"
    else:
        toc_html = '<p class="toc-empty muted">（无章节）</p>'

    sub_chips = []
    if year:
        sub_chips.append(f'<span class="chip">{_esc(year)}</span>')
    if contest:
        sub_chips.append(f'<span class="chip">{_esc(contest)}</span>')
    if track:
        sub_chips.append(f'<span class="chip">{_esc(track)}</span>')
    if repo_url:
        sub_chips.append(
            f'<a class="chip chip-link" href="{_esc(repo_url)}" target="_blank" rel="noopener">🔗 仓库</a>'
        )

    repls = {
        "{{ title }}": f"{team} · 分析报告",
        "{{ team }}": _esc(team),
        "{{ school }}": _esc(school),
        "{{ sub_chips }}": "".join(sub_chips),
        "{{ repo_id }}": _esc(repo_id),
        "{{ summary_cards }}": cards_html,
        "{{ toc }}": toc_html,
        "{{ body_html }}": body_html,  # 已是 trusted html（自己后端生成）
    }
    out = template
    for k, v in repls.items():
        out = out.replace(k, v)
    return out


def _render_report_error(repo_id: str, title: str, hint: str) -> str:
    """报告页友好错误模板（独立、最小依赖）。"""
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>报告未就绪 · {_esc(repo_id)}</title>
<style>
body {{ font-family: -apple-system, "PingFang SC", sans-serif; background: #f5f6fa;
        display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; }}
.box {{ background: white; padding: 2.5rem 3rem; border-radius: 12px;
        box-shadow: 0 4px 16px rgba(0,0,0,.06); text-align: center; max-width: 480px; }}
h1 {{ margin: 0 0 .6rem; color: #b45309; font-size: 1.4rem; }}
p {{ color: #4b5563; line-height: 1.6; }}
code {{ background: #f3f4f6; padding: 2px 6px; border-radius: 4px; font-size: .9em; }}
a {{ display: inline-block; margin-top: 1.4rem; padding: .55rem 1.2rem;
     background: #2563eb; color: white; text-decoration: none; border-radius: 6px; }}
a:hover {{ background: #1d4ed8; }}
</style></head><body>
<div class="box">
  <h1>⚠️ {_esc(title)}</h1>
  <p>仓库 <code>{_esc(repo_id)}</code></p>
  <p>{_esc(hint)}</p>
  <a href="/">← 返回仪表盘</a>
</div>
</body></html>"""


app = create_app()
