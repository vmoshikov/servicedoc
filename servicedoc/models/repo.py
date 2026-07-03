from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, computed_field


class RepoConfig(BaseModel):
    url: str
    branch: str = "main"
    tag: str | None = None
    name: str | None = None  # display name override, when it doesn't match the repo/URL slug
    proto_repo_url: str | None = None  # separate repo holding .proto contracts, if not in this repo
    proto_name: str | None = None  # path segment used to match this service's own .proto files
    # (falls back to `name`) — separate because the display name and the
    # proto-repo directory naming convention don't always agree

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
