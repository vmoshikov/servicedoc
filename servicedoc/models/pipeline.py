from __future__ import annotations

from pathlib import Path
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from .coverage import CoverageResult, TestFile, TestMatchReport
from .docs import ChangelogEntry
from .er import EREntity, ERRelation
from .proto import ProtoMessage, ProtoService
from .repo import ExternalDep, RepoConfig
from .symbols import Symbol

T = TypeVar("T")

_ALWAYS_PRIVATE_DIR_NAMES = frozenset({"priv"})
_NESTED_ONLY_PRIVATE_DIR_NAMES = frozenset({"internal"})
_TEST_DIR_NAMES = frozenset({"test", "tests"})


def _is_test_symbol(s: Symbol, root: Path | None) -> bool:
    """A symbol is test-related if it lives in a _test.go/test_*.py file,
    anywhere under a test/tests directory (helper code with no _test.go
    suffix still counts — it only exists to support tests), or follows Go's
    TestXxx naming convention regardless of where it's defined."""
    name = s.file_path.name
    if name.endswith("_test.go") or name.startswith("test_") or name.endswith("_test.py"):
        return True
    if s.name.startswith("Test"):
        return True
    try:
        rel_parts = s.file_path.relative_to(root).parts[:-1] if root else s.file_path.parts[:-1]
    except ValueError:
        rel_parts = s.file_path.parts[:-1]
    return any(part.lower() in _TEST_DIR_NAMES for part in rel_parts)


class StageResult(BaseModel, Generic[T]):
    stage_name: str
    success: bool
    data: T | None = None
    errors: list[str] = []
    warnings: list[str] = []
    duration_seconds: float = 0.0


class PipelineContext(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    repo_config: RepoConfig
    work_dir: Path
    output_dir: Path

    # накапливается по стадиям
    local_repo_path: Path | None = None
    detected_language: Literal["go", "python", "mixed"] | None = None
    all_source_files: list[Path] = []
    symbols: list[Symbol] = []
    external_deps: list[ExternalDep] = []
    proto_services: list[ProtoService] = []
    proto_messages: list[ProtoMessage] = []
    # structs parsed from generated files (.pb.go, ...) that are excluded from
    # docs entirely — kept only so json_example() can resolve vendored
    # request/response types that have no accompanying .proto in this repo.
    generated_symbols: list[Symbol] = []
    er_entities: list[EREntity] = []
    er_relations: list[ERRelation] = []
    er_diagram: str | None = None
    coverage_result: CoverageResult | None = None
    test_match_report: TestMatchReport | None = None
    # detected independently of whether a coverage report (coverage.out/.xml)
    # was found — TESTS.md must still list test files even with no report.
    detected_test_files: list[TestFile] = []
    git_history: list[ChangelogEntry] = []
    git_tags: list[str] = []
    stage_results: list[StageResult] = Field(default_factory=list)
    # source link helpers
    repo_branch: str = "main"
    source_base_url: str = ""   # normalized repo URL for link generation
    # separate repo holding .proto contracts (proto_repo_url), if configured
    proto_repo_path: Path | None = None
    proto_repo_branch: str = "main"
    proto_repo_base_url: str = ""
    # GLOSSARY.md lives in the servicedoc tool itself (ServiceDocConfig.glossary_path,
    # loaded by PipelineRunner) — shared terminology across every analyzed repo.
    glossary_text: str | None = None
    # FOR_AI.md lives in the analyzed project's own repo (loaded by s01_ingest) —
    # extra project-specific context for the README overview prompt.
    for_ai_text: str | None = None

    @property
    def public_symbols(self) -> list[Symbol]:
        root = self.local_repo_path
        result = []
        for s in self.symbols:
            if not s.is_public:
                continue
            if _is_test_symbol(s, root):
                continue
            if root is not None:
                try:
                    rel_parts = s.file_path.relative_to(root).parts[:-1]
                except ValueError:
                    rel_parts = s.file_path.parts[:-1]
                # "internal" only excludes nested occurrences (e.g. pkg/internal/),
                # not a repo-root-level internal/ — that's where Go convention
                # puts all application code, not "hide from docs".
                if any(part in _ALWAYS_PRIVATE_DIR_NAMES for part in rel_parts):
                    continue
                if any(part in _NESTED_ONLY_PRIVATE_DIR_NAMES for part in rel_parts[1:]):
                    continue
            result.append(s)
        return result

    @property
    def test_symbols(self) -> list[Symbol]:
        """Public functions/methods that are test code (excluded from
        public_symbols) — surfaced separately for TESTS.md's function-level
        coverage matching."""
        root = self.local_repo_path
        return [s for s in self.symbols if s.is_public and _is_test_symbol(s, root)]
