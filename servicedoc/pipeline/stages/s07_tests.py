import logging
from typing import ClassVar

from servicedoc.coverage.parser import find_and_parse
from servicedoc.models.coverage import TestFile, TestMatch, TestMatchReport
from servicedoc.models.pipeline import PipelineContext, StageResult
from servicedoc.pipeline.base import Stage
from servicedoc.utils.fs import is_test_file

logger = logging.getLogger(__name__)

_FUNC_KINDS = ("function", "method")


def _match_tests_to_functions(func_names: list[str], test_names: list[str]) -> TestMatchReport:
    """Approximate name-based matching: strip the "Test" prefix from a test
    name and look for a business function whose name it contains (or is
    contained by). Best-effort — not a real coverage report, just enough to
    tell "this function has a test named after it" from "this is a generic
    integration test that doesn't map to one function"."""
    func_by_lower = {f.lower(): f for f in func_names}
    matched: dict[str, list[str]] = {}
    unmatched: list[str] = []

    for test_name in test_names:
        candidate = test_name[4:] if test_name.startswith("Test") else test_name
        candidate_lower = candidate.lower()
        match: str | None = None
        for fname_lower, fname in func_by_lower.items():
            if not fname_lower:
                continue
            if candidate_lower == fname_lower or candidate_lower.startswith(fname_lower) or fname_lower in candidate_lower:
                match = fname
                break
        if match:
            matched.setdefault(match, []).append(test_name)
        else:
            unmatched.append(test_name)

    return TestMatchReport(
        matches=[TestMatch(function_name=fn, test_names=tests) for fn, tests in matched.items()],
        unmatched_tests=unmatched,
        total_function_count=len(func_names),
    )


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
        ctx.detected_test_files = test_files

        coverage = find_and_parse(ctx.local_repo_path)
        if coverage:
            coverage.test_files = test_files
            ctx.coverage_result = coverage
            logger.info(
                "Coverage: %.1f%% (%d test files)", coverage.overall_pct, len(test_files)
            )
        else:
            logger.info("No coverage report found, detected %d test files", len(test_files))

        func_names = [s.name for s in ctx.public_symbols if s.kind in _FUNC_KINDS]
        test_names = [s.name for s in ctx.test_symbols if s.kind in _FUNC_KINDS]
        ctx.test_match_report = _match_tests_to_functions(func_names, test_names)
        logger.info(
            "Test matching: %d/%d functions have a name-matched test, %d unmatched tests",
            ctx.test_match_report.covered_function_count, len(func_names),
            len(ctx.test_match_report.unmatched_tests),
        )

        return StageResult(
            stage_name=self.name,
            success=True,
            warnings=[] if coverage else ["No coverage report found"],
        )
