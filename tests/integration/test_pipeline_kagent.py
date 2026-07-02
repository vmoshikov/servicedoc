"""
Интеграционный тест на реальном репозитории kagent-dev/kagent.

Требует:
- Доступ к интернету (клонирование github.com)
- AI API (опционально, пропускается если AI__BASE_URL не задан)

Запуск:
    pytest tests/integration/test_pipeline_kagent.py -v -s
"""

import os
from pathlib import Path

import pytest

from servicedoc.config import AIConfig, CacheConfig, GitConfig, ServiceDocConfig
from servicedoc.main import build_pipeline
from servicedoc.models.repo import RepoConfig

KAGENT_URL = "https://github.com/kagent-dev/kagent"
KAGENT_BRANCH = "main"


@pytest.fixture(scope="module")
def kagent_config(tmp_path_factory) -> ServiceDocConfig:
    tmp = tmp_path_factory.mktemp("kagent")
    cfg = ServiceDocConfig(
        ai=AIConfig(
            base_url=os.getenv("AI__BASE_URL", "http://localhost:11434"),
            api_key=os.getenv("AI__API_KEY", ""),
            model=os.getenv("AI__MODEL", "gpt-4o"),
        ),
        git=GitConfig(
            github_token=os.getenv("GIT__GITHUB_TOKEN"),
        ),
        cache=CacheConfig(cache_dir=tmp / "cache"),
        output_dir=tmp / "output",
        skip_stages=["s06_ai_enrich"] if not os.getenv("AI__BASE_URL") else [],
        max_concurrent_parsers=4,
    )
    return cfg


@pytest.mark.asyncio
@pytest.mark.integration
async def test_kagent_ingest(kagent_config):
    """Клонирование репозитория kagent и обнаружение файлов."""
    pipeline = build_pipeline(kagent_config)
    repo_config = RepoConfig(url=KAGENT_URL, branch=KAGENT_BRANCH)
    ctx = await pipeline.run(repo_config)

    # репозиторий клонирован
    assert ctx.local_repo_path is not None
    assert ctx.local_repo_path.exists()

    # язык определён
    assert ctx.detected_language in ("go", "python", "mixed")

    # файлы найдены
    assert len(ctx.all_source_files) > 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_kagent_symbols_extracted(kagent_config):
    """Проверяет что публичные символы успешно извлечены."""
    pipeline = build_pipeline(kagent_config)
    repo_config = RepoConfig(url=KAGENT_URL, branch=KAGENT_BRANCH)
    ctx = await pipeline.run(repo_config)

    assert len(ctx.symbols) > 0
    public = ctx.public_symbols
    assert len(public) > 0

    # все публичные символы имеют имя и файл
    for sym in public[:10]:
        assert sym.name
        assert sym.file_path.exists()
        assert sym.line_start > 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_kagent_docs_generated(kagent_config):
    """Проверяет что документация сгенерирована."""
    pipeline = build_pipeline(kagent_config)
    repo_config = RepoConfig(url=KAGENT_URL, branch=KAGENT_BRANCH)
    ctx = await pipeline.run(repo_config)

    output_dir = kagent_config.output_dir
    assert (output_dir / "README.md").exists()
    assert (output_dir / "API.md").exists()
    assert (output_dir / "TESTS.md").exists()

    readme = (output_dir / "README.md").read_text(encoding="utf-8")
    assert "kagent" in readme.lower()
    assert "<!-- @ai:document" in readme


@pytest.mark.asyncio
@pytest.mark.integration
async def test_kagent_proto_parsed(kagent_config):
    """Если в kagent есть .proto файлы — проверяем их парсинг."""
    pipeline = build_pipeline(kagent_config)
    repo_config = RepoConfig(url=KAGENT_URL, branch=KAGENT_BRANCH)
    ctx = await pipeline.run(repo_config)

    # proto могут быть или нет — просто проверяем что этап не упал
    s04 = next((r for r in ctx.stage_results if r.stage_name == "s04_proto"), None)
    assert s04 is not None
    # если proto есть — они распарсены без фатальных ошибок
    if ctx.proto_services:
        for svc in ctx.proto_services:
            assert svc.name
            assert svc.file_path.exists()
