from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, computed_field


class RepoConfig(BaseModel):
    url: str
    branch: str = "main"
    tag: str | None = None

    @computed_field
    @property
    def slug(self) -> str:
        return hashlib.sha256(self.url.encode()).hexdigest()[:16]


class Dependency(BaseModel):
    name: str
    version: str
    git_url: str | None = None
    is_external_git: bool = False

    @computed_field
    @property
    def slug(self) -> str:
        return hashlib.sha256(self.name.encode()).hexdigest()[:16]


class ExternalDep(BaseModel):
    dependency: Dependency
    clone_path: Path
    imported_symbols: list[str] = []
    analyzed_files: list[Path] = []
    language: Literal["go", "python", "unknown"] = "unknown"
