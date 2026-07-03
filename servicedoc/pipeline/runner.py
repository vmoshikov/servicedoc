import logging
import time
from pathlib import Path

from servicedoc.config import ServiceDocConfig
from servicedoc.models.pipeline import PipelineContext, StageResult
from servicedoc.models.repo import RepoConfig

from .base import Stage

logger = logging.getLogger(__name__)


class PipelineFatalError(Exception):
    def __init__(self, stage_name: str, cause: Exception) -> None:
        super().__init__(f"Stage '{stage_name}' failed fatally: {cause}")
        self.stage_name = stage_name
        self.cause = cause


class PipelineRunner:
    def __init__(self, stages: list[Stage], config: ServiceDocConfig) -> None:
        self.stages = stages
        self.config = config

    async def run(self, repo_config: RepoConfig) -> PipelineContext:
        work_dir = self.config.cache.cache_dir / repo_config.slug
        work_dir.mkdir(parents=True, exist_ok=True)
        output_dir = self.config.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        ctx = PipelineContext(
            repo_config=repo_config,
            work_dir=work_dir,
            output_dir=output_dir,
        )
        try:
            ctx.glossary_text = self.config.glossary_path.read_text(encoding="utf-8").strip() or None
        except OSError:
            ctx.glossary_text = None

        for stage in self.stages:
            if stage.name in self.config.skip_stages:
                logger.info("Skipping stage: %s", stage.name)
                continue

            if not await stage.validate_input(ctx):
                logger.warning("Stage %s: input validation failed, skipping", stage.name)
                continue

            t0 = time.monotonic()
            logger.info("Running stage: %s", stage.name)
            try:
                result = await stage.run(ctx)
                result.duration_seconds = time.monotonic() - t0
                ctx.stage_results.append(result)
                if not result.success:
                    logger.warning("Stage %s completed with errors: %s", stage.name, result.errors)
                    if stage.required:
                        raise PipelineFatalError(stage.name, Exception("; ".join(result.errors)))
            except PipelineFatalError:
                raise
            except Exception as exc:
                duration = time.monotonic() - t0
                result = StageResult(
                    stage_name=stage.name,
                    success=False,
                    errors=[str(exc)],
                    duration_seconds=duration,
                )
                ctx.stage_results.append(result)
                logger.exception("Stage %s raised exception", stage.name)
                if stage.required:
                    raise PipelineFatalError(stage.name, exc) from exc

        return ctx
