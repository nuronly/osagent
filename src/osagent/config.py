"""统一配置：从 .env / 环境变量加载。"""
from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ===== LLM =====
    deepseek_api_key: str = Field(default="", description="DeepSeek API Key")
    deepseek_base_url: str = Field(default="https://api.deepseek.com")
    deepseek_model: str = Field(default="deepseek-chat")

    # ===== 运行时 =====
    log_level: str = Field(default="INFO")
    data_dir: Path = Field(default=PROJECT_ROOT / "data")

    # ===== Git =====
    git_clone_timeout: int = Field(default=120)
    git_clone_depth: int = Field(default=0, description="0=完整历史；>0=浅克隆深度")
    git_concurrency: int = Field(default=4)

    # ===== 数据源 =====
    dataset_xlsx: Path = Field(default=PROJECT_ROOT / "collected-data.xlsx")

    # ===== 常用派生路径 =====
    @property
    def repos_dir(self) -> Path:
        return self.data_dir / "repos"

    @property
    def facts_dir(self) -> Path:
        return self.data_dir / "facts"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def reports_dir(self) -> Path:
        return self.data_dir / "reports"

    @property
    def manifest_path(self) -> Path:
        return self.data_dir / "manifest.json"

    def ensure_dirs(self) -> None:
        for p in [
            self.data_dir,
            self.repos_dir,
            self.facts_dir,
            self.cache_dir,
            self.reports_dir,
        ]:
            p.mkdir(parents=True, exist_ok=True)


settings = Settings()
