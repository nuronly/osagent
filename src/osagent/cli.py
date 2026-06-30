"""osAgent 命令行入口（Typer）。

子命令：
- llm        LLM 相关（ping ...）
- manifest   仓库清单（build / stats / show）
- ingest     仓库拉取（probe / clone-all / clone）
- analyzer   静态分析（list-tools ...）
"""
from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.table import Table

from .analyzer import analyze_by_repo_id, has_facts, list_mcp_tools, load_facts
from .config import settings
from .ingest import (
    build_manifest,
    clone_many,
    clone_one,
    load_manifest,
    manifest_stats,
    sample_probe,
)
from .llm import get_client
from .logging import logger
from .schemas import RepoStatus

app = typer.Typer(help="osAgent: 面向小型操作系统的分析比对智能体系统")
console = Console()

llm_app = typer.Typer(help="LLM 相关命令")
manifest_app = typer.Typer(help="仓库清单管理")
ingest_app = typer.Typer(help="仓库拉取")
analyzer_app = typer.Typer(help="静态分析")
report_app = typer.Typer(help="分析报告生成")

app.add_typer(llm_app, name="llm")
app.add_typer(manifest_app, name="manifest")
app.add_typer(ingest_app, name="ingest")
app.add_typer(analyzer_app, name="analyzer")
app.add_typer(report_app, name="report")


@app.command("serve")
def serve(
    host: str = typer.Option("127.0.0.1", help="绑定地址；公网访问改 0.0.0.0"),
    port: int = typer.Option(8765, help="端口"),
    reload: bool = typer.Option(False, "--reload", help="开发模式自动重载"),
) -> None:
    """启动 Web 仪表盘（FastAPI + 静态前端）。"""
    import uvicorn
    console.print(f"[green]osAgent Web 启动:[/green] http://{host}:{port}")
    uvicorn.run("osagent.web.app:app", host=host, port=port, reload=reload)


# ============ llm ============

@llm_app.command("ping")
def llm_ping() -> None:
    """测试 DeepSeek API 连通性。"""
    try:
        result = get_client().ping()
    except Exception as e:
        console.print(f"[red]LLM ping 失败:[/red] {e}")
        raise typer.Exit(1) from e
    console.print("[green]LLM ping 成功[/green]")
    console.print_json(json.dumps(result, ensure_ascii=False))


# ============ manifest ============

@manifest_app.command("build")
def manifest_build(
    xlsx: str = typer.Option(None, help="数据源 xlsx 路径（默认 settings.dataset_xlsx）"),
) -> None:
    """从 collected-data.xlsx 构建 / 更新 manifest.json。"""
    from pathlib import Path
    xlsx_path = Path(xlsx) if xlsx else None
    m = build_manifest(xlsx_path=xlsx_path)
    console.print(f"[green]ok[/green]  total={m.total}, 写入 {settings.manifest_path}")


@manifest_app.command("stats")
def manifest_stats_cmd() -> None:
    """查看 manifest 各维度分布。"""
    m = load_manifest()
    stats = manifest_stats(m)

    t = Table(title="Manifest 概览", show_header=True)
    t.add_column("维度", style="cyan")
    t.add_column("值")
    t.add_row("总数", str(stats["total"]))
    t.add_row("学校数", str(stats["schools_count"]))
    t.add_row("年份分布", json.dumps(stats["by_year"], ensure_ascii=False))
    t.add_row("Host 分布", json.dumps(stats["by_host"], ensure_ascii=False))
    t.add_row("Track 分布", json.dumps(stats["by_track"], ensure_ascii=False))
    t.add_row("Status 分布", json.dumps(stats["by_status"], ensure_ascii=False))
    console.print(t)


@manifest_app.command("show")
def manifest_show(
    year: int = typer.Option(None, help="按年份过滤"),
    status: str = typer.Option(None, help="按 status 过滤 (ok/pending/unreachable/timeout/error)"),
    limit: int = typer.Option(20, help="最多展示条数"),
) -> None:
    """展示 manifest 中的仓库列表。"""
    m = load_manifest()
    repos = m.repos
    if year:
        repos = [r for r in repos if r.year == year]
    if status:
        repos = [r for r in repos if r.status.value == status]

    t = Table(title=f"Repos (showing {min(limit, len(repos))} / {len(repos)})", show_header=True)
    t.add_column("year", style="cyan")
    t.add_column("repo_id")
    t.add_column("school")
    t.add_column("team")
    t.add_column("host")
    t.add_column("status")
    for r in repos[:limit]:
        color = {"ok": "green", "pending": "yellow"}.get(r.status.value, "red")
        t.add_row(
            str(r.year), r.repo_id, r.school, r.team, r.host,
            f"[{color}]{r.status.value}[/{color}]",
        )
    console.print(t)


# ============ ingest ============

@ingest_app.command("probe")
def ingest_probe(
    n: int = typer.Option(5, "-n", help="抽样个数"),
    depth: int = typer.Option(1, help="git clone --depth"),
    seed: int = typer.Option(42, help="随机种子"),
) -> None:
    """随机抽 N 个仓库做连通性探测（默认浅克隆）。"""
    m = load_manifest()
    sample_probe(m, n=n, seed=seed, depth=depth)

    # 打印结果
    stats = manifest_stats(m)
    console.print("[bold]抽样结果（已写回 manifest）：[/bold]")
    console.print_json(json.dumps(stats["by_status"], ensure_ascii=False))


@ingest_app.command("clone-all")
def ingest_clone_all(
    force: bool = typer.Option(False, "--force", help="强制重拉已存在的仓库"),
    concurrency: int = typer.Option(None, help="并发数（默认读 settings）"),
    depth: int = typer.Option(None, help="git clone --depth；0/省略=完整历史"),
    only_pending: bool = typer.Option(
        True, help="只拉 pending / 失败的仓库（推荐）；False 则全部重过一遍",
    ),
) -> None:
    """批量拉取所有仓库。"""
    m = load_manifest()
    if only_pending and not force:
        targets = [r for r in m.repos if r.status != RepoStatus.OK]
    else:
        targets = m.repos
    logger.info(f"待克隆: {len(targets)} / {m.total}")
    clone_many(m, entries=targets, force=force, concurrency=concurrency, depth=depth)
    stats = manifest_stats(m)
    console.print(json.dumps(stats["by_status"], ensure_ascii=False, indent=2))


@ingest_app.command("clone")
def ingest_clone_one(
    repo_id: str = typer.Argument(..., help="单个 repo_id"),
    force: bool = typer.Option(False, "--force"),
    depth: int = typer.Option(None),
) -> None:
    """克隆指定 repo_id 的单个仓库（调试用）。"""
    m = load_manifest()
    target = next((r for r in m.repos if r.repo_id == repo_id), None)
    if not target:
        console.print(f"[red]repo_id 未找到: {repo_id}[/red]")
        raise typer.Exit(1)
    clone_one(target, force=force, depth=depth)
    from .ingest import save_manifest
    save_manifest(m)
    console.print(f"status = {target.status.value}, local = {target.local_path}")


# ============ analyzer ============

@analyzer_app.command("list-tools")
def analyzer_list_tools() -> None:
    """列出 Static Analyzer 对外暴露的 MCP 工具契约（W3 之前仅 schema）。"""
    tools = list_mcp_tools()
    t = Table(title=f"MCP Static Analyzer Tools ({len(tools)})", show_header=True)
    t.add_column("name", style="cyan")
    t.add_column("description")
    for spec in tools:
        t.add_row(spec.name, spec.description)
    console.print(t)


@analyzer_app.command("analyze")
def analyzer_analyze(
    repo_id: str = typer.Argument(..., help="manifest 中的 repo_id"),
    level: str = typer.Option("L2", help="分析深度: L1 / L2 / L3"),
    budget: float = typer.Option(30.0, help="L2 函数索引时间预算（秒）"),
    force: bool = typer.Option(False, "--force", help="即使事实表已存在也重算"),
) -> None:
    """对单个仓库执行静态分析，生成事实表。"""
    if level not in {"L1", "L2", "L3"}:
        console.print(f"[red]level 必须是 L1/L2/L3，得到: {level}[/red]")
        raise typer.Exit(1)

    if has_facts(repo_id) and not force:
        console.print(
            f"[yellow]事实表已存在: {repo_id}，加 --force 重算；"
            f"现仅打印摘要[/yellow]"
        )
        f = load_facts(repo_id)
        console.print(f.summary_for_embedding)
        return

    def _on_progress(stage: str, msg: str, pct: int) -> None:
        console.print(f"[cyan][{pct:3d}%][/cyan] [{stage}] {msg}")

    facts = analyze_by_repo_id(
        repo_id,
        level=level,  # type: ignore[arg-type]
        on_progress=_on_progress,
        l2_budget_seconds=budget,
    )
    console.print(f"[green]done.[/green]")
    console.print(facts.summary_for_embedding, markup=False)


@analyzer_app.command("show")
def analyzer_show(
    repo_id: str = typer.Argument(...),
    section: str = typer.Option(
        "summary",
        help="summary / basics / subsystems / syscalls / functions / history",
    ),
) -> None:
    """查看已生成的事实表。"""
    if not has_facts(repo_id):
        console.print(f"[red]事实表不存在，请先 `osagent analyzer analyze {repo_id}`[/red]")
        raise typer.Exit(1)
    f = load_facts(repo_id)
    sec = section.lower()
    if sec == "summary":
        console.print(f.summary_for_embedding, markup=False)
    elif sec == "basics":
        console.print_json(f.basics.model_dump_json(indent=2))
    elif sec == "subsystems":
        t = Table(title=f"Subsystems ({len(f.kernel_features)})")
        t.add_column("feature", style="cyan")
        t.add_column("files")
        t.add_column("confidence")
        for kf in f.kernel_features:
            t.add_row(kf.feature, str(len(kf.files)), kf.confidence)
        console.print(t)
    elif sec == "syscalls":
        t = Table(title=f"Syscalls ({f.syscalls.count})")
        t.add_column("name", style="cyan")
        t.add_column("handler_file")
        for s in f.syscalls.items[:50]:
            t.add_row(s.name, s.handler_file or "-")
        console.print(t)
        if f.syscalls.count > 50:
            console.print(f"... 共 {f.syscalls.count} 条，仅展示前 50")
    elif sec == "functions":
        console.print(f"函数节点总数: {len(f.call_graph.nodes)}")
        for n in f.call_graph.nodes[:20]:
            console.print(f"  {n.qualified_name}  ({n.file}:{n.start_line})")
    elif sec == "history":
        h = f.dev_history
        console.print(
            f"commits={h.commits_total}, contributors={h.contributors_total}, "
            f"first={h.first_commit_at}, last={h.last_commit_at}"
        )
    else:
        console.print(f"[red]未知 section: {section}[/red]")
        raise typer.Exit(1)


# ============ report ============

@report_app.command("build")
def report_build(
    repo_id: str = typer.Argument(..., help="manifest 中的 repo_id"),
    fmt: str = typer.Option("both", help="md / html / both"),
    analyze_if_missing: bool = typer.Option(
        True, "--analyze/--no-analyze",
        help="事实表缺失时是否自动跑一次 L2 分析",
    ),
) -> None:
    """生成单仓库的分析报告（Markdown + HTML，落盘到 data/reports/）。"""
    from .report import build_report
    if fmt not in {"md", "html", "both"}:
        console.print(f"[red]fmt 必须是 md/html/both，得到: {fmt}[/red]")
        raise typer.Exit(1)

    if not has_facts(repo_id):
        if not analyze_if_missing:
            console.print(
                f"[red]事实表不存在: {repo_id}。先 `osagent analyzer analyze {repo_id}`，"
                f"或加 --analyze[/red]"
            )
            raise typer.Exit(1)
        console.print(f"[yellow]事实表不存在，自动跑 L2 分析: {repo_id}[/yellow]")

        def _on_progress(stage, msg, pct):
            console.print(f"[cyan][{pct:3d}%][/cyan] [{stage}] {msg}")

        analyze_by_repo_id(repo_id, level="L2", on_progress=_on_progress)

    out = build_report(repo_id, fmt=fmt)  # type: ignore[arg-type]
    console.print(f"[green]done.[/green]")
    if "md_path" in out:
        console.print(f"  md   → {out['md_path']}  ({out.get('md_chars', 0):,} chars)")
    if "html_path" in out:
        console.print(f"  html → {out['html_path']}  ({out.get('html_chars', 0):,} chars)")


@report_app.command("build-all")
def report_build_all(
    fmt: str = typer.Option("both", help="md / html / both"),
) -> None:
    """对所有已生成事实表的仓库批量生成报告。"""
    from .analyzer.storage import facts_dir
    from .report import build_report

    fd = facts_dir()
    repo_ids = sorted(p.stem for p in fd.glob("*.json"))
    if not repo_ids:
        console.print("[yellow]没有可用的事实表，先跑 analyzer analyze[/yellow]")
        raise typer.Exit(1)

    console.print(f"[bold]将生成 {len(repo_ids)} 份报告[/bold]")
    for rid in repo_ids:
        try:
            out = build_report(rid, fmt=fmt)  # type: ignore[arg-type]
            md = out.get("md_chars", 0)
            html_ = out.get("html_chars", 0)
            console.print(f"  [green]ok[/green] {rid:40s} md={md:>6,} html={html_:>6,}")
        except Exception as e:
            console.print(f"  [red]fail[/red] {rid}  {e}")


if __name__ == "__main__":
    app()
