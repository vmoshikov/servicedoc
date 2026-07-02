import logging
from typing import ClassVar

from servicedoc.git.cloner import GitCloner, parse_url_branch
from servicedoc.models.pipeline import PipelineContext, StageResult
from servicedoc.pipeline.base import Stage
from servicedoc.utils.fs import detect_language, walk_source_files

logger = logging.getLogger(__name__)


def _service_name_from_url(url: str) -> str:
    clean_url, _ = parse_url_branch(url)
    return clean_url.rstrip("/").split("/")[-1].removesuffix(".git")


def _normalize_repo_url(url: str) -> str:
    clean_url, _ = parse_url_branch(url)
    return clean_url.rstrip("/").removesuffix(".git")


class RepoIngestionStage(Stage):
    name: ClassVar[str] = "s01_ingest"
    required: ClassVar[bool] = True

    def __init__(self, cloner: GitCloner) -> None:
        self.cloner = cloner

    async def run(self, ctx: PipelineContext) -> StageResult:
        # per-project output subdir: servicedoc_output/{project_name}/
        service_name = _service_name_from_url(ctx.repo_config.url)
        ctx.output_dir = ctx.output_dir / service_name
        ctx.output_dir.mkdir(parents=True, exist_ok=True)

        ctx.source_base_url = _normalize_repo_url(ctx.repo_config.url)

        repo_dir = ctx.work_dir / "repo"
        branch = await self.cloner.clone(
            url=ctx.repo_config.url,
            target_dir=repo_dir,
            branch=ctx.repo_config.branch,
        )
        ctx.local_repo_path = repo_dir

        # detect actual checked-out branch
        try:
            import git
            repo = git.Repo(repo_dir)
            ctx.repo_branch = repo.active_branch.name
        except Exception:
            ctx.repo_branch = ctx.repo_config.branch

        files = []
        async for f in walk_source_files(repo_dir):
            files.append(f)
        ctx.all_source_files = files

        lang = detect_language(files)
        ctx.detected_language = lang  # type: ignore[assignment]

        logger.info(
            "Ingested %s: %d source files, language=%s, branch=%s",
            service_name, len(files), lang, ctx.repo_branch,
        )
        return StageResult(stage_name=self.name, success=True)
