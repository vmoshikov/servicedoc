from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel


class ChangelogEntry(BaseModel):
    sha: str
    message: str
    author: str
    date: datetime
    tag: str | None = None
    scope: str | None = None
    breaking: bool = False
    kind: Literal["feat", "fix", "refactor", "chore", "docs", "test", "ci", "other"] = "other"
    cluster_representative: bool = True


class ReleaseNote(BaseModel):
    tag: str
    prev_tag: str | None = None
    date: datetime
    ai_summary: str | None = None
    changelog_entries: list[ChangelogEntry] = []
    changed_files_count: int = 0
    added_lines: int = 0
    removed_lines: int = 0
    changed_symbols: list[str] = []


class DocOutput(BaseModel):
    path: Path
    content: str
    doc_type: str
