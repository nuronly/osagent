"""冒烟测试：基础导入与 schema 创建都不报错。"""
from osagent import __version__
from osagent.analyzer import list_mcp_tools
from osagent.schemas import (
    Basics,
    BuildSystem,
    LanguageStat,
    Manifest,
    RepoEntry,
    RepoStatus,
)


def test_version():
    assert __version__


def test_manifest_roundtrip():
    e = RepoEntry(
        year=2025,
        contest="操作系统赛",
        track="内核实现赛道",
        school="清华大学",
        team="MockTeam",
        repo_url="https://example.com/mock.git",
        repo_id="2025_001_MockTeam",
        host="other",
        status=RepoStatus.PENDING,
    )
    m = Manifest(source_xlsx="mock.xlsx", total=1, repos=[e])
    js = m.model_dump_json()
    m2 = Manifest.model_validate_json(js)
    assert m2.total == 1
    assert m2.repos[0].repo_id == "2025_001_MockTeam"


def test_basics_schema():
    b = Basics(
        languages=[LanguageStat(language="Rust", loc=1000, percent=80.0)],
        total_loc=1250,
        arch=["riscv64"],
        build=BuildSystem(kind="cargo", files=["Cargo.toml"]),
    )
    assert b.total_loc == 1250


def test_mcp_tools_listed():
    tools = list_mcp_tools()
    assert len(tools) >= 8
    names = {t.name for t in tools}
    assert "repo.full_facts" in names
    assert "kernel.extract_syscalls" in names
