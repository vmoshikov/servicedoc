import logging
from pathlib import Path
from typing import ClassVar

from servicedoc.git.cloner import GitCloner, parse_url_branch
from servicedoc.models.pipeline import PipelineContext, StageResult
from servicedoc.pipeline.base import Stage
from servicedoc.proto.parser import ProtoFileParser

logger = logging.getLogger(__name__)


def _normalize_repo_url(url: str) -> str:
    clean_url, _ = parse_url_branch(url)
    return clean_url.rstrip("/").removesuffix(".git")


class ProtoParsingStage(Stage):
    name: ClassVar[str] = "s04_proto"
    required: ClassVar[bool] = False

    def __init__(self, cloner: GitCloner | None = None) -> None:
        self.cloner = cloner

    async def _clone_proto_repo(self, ctx: PipelineContext, errors: list[str]) -> None:
        """Clone a separate repo holding .proto contracts, if configured —
        vendored .pb.go often ships with no .proto alongside it in the
        service's own repo (contracts live in a shared repo instead)."""
        proto_repo_url = ctx.repo_config.proto_repo_url
        if not proto_repo_url or not self.cloner:
            return
        clean_url, branch = parse_url_branch(proto_repo_url)
        try:
            proto_repo_dir = ctx.work_dir / "proto_repo"
            await self.cloner.clone(url=clean_url, target_dir=proto_repo_dir, branch=branch or "main")
            ctx.proto_repo_path = proto_repo_dir
            ctx.proto_repo_base_url = _normalize_repo_url(clean_url)
            try:
                import git
                ctx.proto_repo_branch = git.Repo(proto_repo_dir).active_branch.name
            except Exception:
                ctx.proto_repo_branch = branch or "main"
        except Exception as exc:
            errors.append(f"proto repo clone failed: {exc}")
            logger.warning("Proto repo clone failed: %s", exc)

    async def run(self, ctx: PipelineContext) -> StageResult:
        if not ctx.local_repo_path:
            return StageResult(stage_name=self.name, success=False, errors=["No repo path"])

        errors: list[str] = []
        await self._clone_proto_repo(ctx, errors)

        proto_roots = [ctx.local_repo_path]
        if ctx.proto_repo_path:
            proto_roots.append(ctx.proto_repo_path)

        proto_files: list[Path] = []
        for root in proto_roots:
            proto_files.extend(root.rglob("*.proto"))

        if not proto_files:
            logger.info("No .proto files found")
            return StageResult(
                stage_name=self.name, success=True,
                warnings=["No .proto files found"], errors=errors,
            )

        parser = ProtoFileParser()
        for proto_file in proto_files:
            try:
                services, messages = parser.parse(proto_file)
                ctx.proto_services.extend(services)
                ctx.proto_messages.extend(messages)
            except Exception as exc:
                errors.append(f"{proto_file}: {exc}")
                logger.warning("Proto parse error %s: %s", proto_file, exc)

        logger.info(
            "Parsed %d proto services, %d messages from %d files",
            len(ctx.proto_services), len(ctx.proto_messages), len(proto_files),
        )
        return StageResult(stage_name=self.name, success=True, errors=errors)
