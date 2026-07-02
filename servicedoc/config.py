from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AIConfig(BaseSettings):
    base_url: str = Field(..., description="Base URL for OpenAI-compatible API")
    api_key: str = ""
    model: str = "gpt-4o"
    max_tokens: int = 2048
    batch_size: int = 10
    rate_limit_rpm: int = 60
    retry_max_attempts: int = 5
    retry_base_delay_seconds: float = 2.0


class GitConfig(BaseSettings):
    github_token: str | None = None
    gitlab_token: str | None = None
    clone_timeout_seconds: int = 120


class CacheConfig(BaseSettings):
    cache_dir: Path = Path("/tmp/servicedoc_cache")
    clone_cache_ttl_seconds: int = 86400
    ai_response_cache: bool = True


class ServiceDocConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_nested_delimiter="__",
        extra="ignore",
    )

    ai: AIConfig = Field(default_factory=lambda: AIConfig(base_url="http://localhost:11434"))
    git: GitConfig = Field(default_factory=GitConfig)
    cache: CacheConfig = Field(default_factory=CacheConfig)
    output_dir: Path = Path("./servicedoc_output")
    max_concurrent_parsers: int = 8
    max_concurrent_ai_calls: int = 3
    skip_stages: list[str] = []
    report_language: str = "ru"
