from __future__ import annotations

from pathlib import Path
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from .coverage import CoverageResult
from .docs import ChangelogEntry
from .er import EREntity, ERRelation
from .proto import ProtoService
from .repo import ExternalDep, RepoConfig
from .symbols import Symbol

T = TypeVar("T")


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

    @property
    def public_symbols(self) -> list[Symbol]:
        return [s for s in self.symbols if s.is_public]
