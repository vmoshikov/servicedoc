import logging
from typing import ClassVar

from servicedoc.coverage.parser import find_and_parse
from servicedoc.models.coverage import TestFile
from servicedoc.models.pipeline import PipelineContext, StageResult
from servicedoc.pipeline.base import Stage
from servicedoc.utils.fs import is_test_file

logger = logging.getLogger(__name__)


class TestCoverageStage(Stage):
    name: ClassVar[str] = "s07_tests"
    required: ClassVar[bool] = False

    async def run(self, ctx: PipelineContext) -> StageResult:
        if not ctx.local_repo_path:
            return StageResult(stage_name=self.name, success=False, errors=["No repo path"])

        test_files = [
            TestFile(path=f, language=("go" if f.suffix == ".go" else "python"))
            for f in ctx.all_source_files
            if is_test_file(f)
        ]

        coverage = find_and_parse(ctx.local_repo_path)
        if coverage:
            coverage.test_files = test_files
            ctx.coverage_result = coverage
            logger.info(
                "Coverage: %.1f%% (%d test files)", coverage.overall_pct, len(test_files)
            )
        else:
            logger.info("No coverage report found, detected %d test files", len(test_files))

        return StageResult(
            stage_name=self.name,
            success=True,
            warnings=[] if coverage else ["No coverage report found"],
        )
