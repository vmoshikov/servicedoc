from __future__ import annotations

from pathlib import Path
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from .coverage import CoverageResult
from .docs import ChangelogEntry
from .er import EREntity, ERRelation
from .proto import ProtoMessage, ProtoService
from .repo import ExternalDep, RepoConfig
from .symbols import Symbol

T = TypeVar("T")

_ALWAYS_PRIVATE_DIR_NAMES = frozenset({"priv"})
_NESTED_ONLY_PRIVATE_DIR_NAMES = frozenset({"internal"})


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

    @property
    def public_symbols(self) -> list[Symbol]:
        root = self.local_repo_path
        result = []
        for s in self.symbols:
            if not s.is_public:
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
