import logging
from pathlib import Path
from typing import ClassVar

from servicedoc.git.cloner import GitCloner
from servicedoc.models.pipeline import PipelineContext, StageResult
from servicedoc.models.repo import Dependency, ExternalDep
from servicedoc.pipeline.base import Stage
from servicedoc.parsers.go.dep_parser import parse_go_mod
from servicedoc.parsers.python.dep_parser import parse_pyproject, parse_requirements

logger = logging.getLogger(__name__)


class DependencyResolutionStage(Stage):
    name: ClassVar[str] = "s02_deps"
    required: ClassVar[bool] = False

    def __init__(self, cloner: GitCloner, deps_cache_dir: Path) -> None:
        self.cloner = cloner
        self.deps_cache_dir = deps_cache_dir

    async def run(self, ctx: PipelineContext) -> StageResult:
        if not ctx.local_repo_path:
            return StageResult(stage_name=self.name, success=False, errors=["No repo path"])

        repo = ctx.local_repo_path
        deps: list[Dependency] = []

        go_mod = repo / "go.mod"
        if go_mod.exists():
            deps.extend(parse_go_mod(go_mod))

        pyproject = repo / "pyproject.toml"
        if pyproject.exists():
            try:
                deps.extend(parse_pyproject(pyproject))
            except Exception as exc:
                logger.warning("pyproject.toml parse error: %s", exc)

        req = repo / "requirements.txt"
        if req.exists():
            deps.extend(parse_requirements(req))

        external = [d for d in deps if d.is_external_git and d.git_url]
        logger.info("Found %d external git dependencies", len(external))

        external_deps: list[ExternalDep] = []
        for dep in external:
            if not dep.git_url:
                continue
            target = self.deps_cache_dir / dep.slug
            try:
                await self.cloner.clone(dep.git_url, target)
                lang = "go" if (target / "go.mod").exists() else "python"
                external_deps.append(ExternalDep(
                    dependency=dep,
                    clone_path=target,
                    language=lang,
                ))
            except Exception as exc:
                logger.warning("Failed to clone dep %s: %s", dep.name, exc)

        ctx.external_deps = external_deps
        return StageResult(stage_name=self.name, success=True)
