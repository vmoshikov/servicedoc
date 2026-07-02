from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Annotated

import typer

from servicedoc.config import ServiceDocConfig
from servicedoc.models.repo import RepoConfig

app = typer.Typer(
    name="servicedoc",
    help="Automated code analysis and documentation generation.",
    pretty_exceptions_enable=False,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


def build_pipeline(cfg: ServiceDocConfig):
    from servicedoc.ai.client import AIClient
    from servicedoc.git.cloner import GitCloner
    from servicedoc.parsers.registry import ParserRegistry
    from servicedoc.pipeline.runner import PipelineRunner
    from servicedoc.pipeline.stages.s01_ingest import RepoIngestionStage
    from servicedoc.pipeline.stages.s02_deps import DependencyResolutionStage
    from servicedoc.pipeline.stages.s03_parse import CodeParsingStage
    from servicedoc.pipeline.stages.s04_proto import ProtoParsingStage
    from servicedoc.pipeline.stages.s05_comments import CommentExtractionStage
    from servicedoc.pipeline.stages.s06_ai_enrich import AIEnrichmentStage
    from servicedoc.pipeline.stages.s07_tests import TestCoverageStage
    from servicedoc.pipeline.stages.s08_er import ERDiagramStage
    from servicedoc.pipeline.stages.s09_docs import DocumentationStage

    cloner = GitCloner(cfg.git, cfg.cache.cache_dir)
    registry = ParserRegistry.default()
    ai_client = AIClient(cfg.ai) if cfg.ai.base_url else None

    stages = [
        RepoIngestionStage(cloner),
        DependencyResolutionStage(cloner, cfg.cache.cache_dir / "deps"),
        CodeParsingStage(registry, cfg.max_concurrent_parsers),
        ProtoParsingStage(),
        CommentExtractionStage(),
        AIEnrichmentStage(ai_client, cfg.ai.batch_size, cfg.max_concurrent_ai_calls)
        if ai_client else CommentExtractionStage(),
        TestCoverageStage(),
        ERDiagramStage(),
        DocumentationStage(ai_client),
    ]
    return PipelineRunner(stages, cfg)


@app.command()
def analyze(
    url: Annotated[str, typer.Argument(help="Git URL of the target repository")],
    branch: Annotated[str, typer.Option("--branch", "-b")] = "main",
    output: Annotated[Path, typer.Option("--output", "-o")] = Path("./servicedoc_output"),
    skip: Annotated[list[str], typer.Option("--skip", "-s")] = [],
    config_file: Annotated[Path | None, typer.Option("--config", "-c")] = None,
) -> None:
    """Analyze a git repository and generate documentation."""
    env_file = str(config_file) if config_file else ".env"
    cfg = ServiceDocConfig(_env_file=env_file)
    cfg.output_dir = output
    cfg.skip_stages = list(skip)

    pipeline = build_pipeline(cfg)
    repo_config = RepoConfig(url=url, branch=branch)

    typer.echo(f"Analyzing: {url}")
    ctx = asyncio.run(pipeline.run(repo_config))

    success_stages = sum(1 for r in ctx.stage_results if r.success)
    typer.echo(f"Done: {success_stages}/{len(ctx.stage_results)} stages succeeded")
    typer.echo(f"Output: {ctx.output_dir.resolve()}")


@app.command()
def serve(
    host: str = "0.0.0.0",
    port: int = 8080,
) -> None:
    """Start REST API server for analysis triggering."""
    try:
        import uvicorn
        from servicedoc.api import app as fastapi_app
        uvicorn.run(fastapi_app, host=host, port=port)
    except ImportError:
        typer.echo("Install 'api' extras: pip install servicedoc[api]", err=True)
        sys.exit(1)


if __name__ == "__main__":
    app()
