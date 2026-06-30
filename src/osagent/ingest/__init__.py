"""仓库拉取与清单管理。"""
from .cloner import clone_many, clone_one, sample_probe
from .manifest import (
    add_repo_manual,
    backup_manifest,
    build_manifest,
    delete_repo,
    import_xlsx_incremental,
    load_manifest,
    manifest_stats,
    save_manifest,
)

__all__ = [
    "build_manifest",
    "load_manifest",
    "save_manifest",
    "manifest_stats",
    "clone_one",
    "clone_many",
    "sample_probe",
    # v0.7 增量
    "add_repo_manual",
    "backup_manifest",
    "delete_repo",
    "import_xlsx_incremental",
]
