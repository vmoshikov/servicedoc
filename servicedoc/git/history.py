import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

import git

from servicedoc.models.docs import ChangelogEntry

logger = logging.getLogger(__name__)

_CONVENTIONAL = re.compile(
    r"^(?P<kind>feat|fix|refactor|chore|docs|test|ci|perf|style|build|revert)"
    r"(?:\((?P<scope>[^)]+)\))?(?P<breaking>!)?\s*:\s*(?P<msg>.+)$",
    re.IGNORECASE,
)
_MD_SPECIAL_CHARS = re.compile(r"([`*_\[\]<>|])")


def _sanitize_message(text: str) -> str:
    """Changelog only cares about the commit subject line — a multi-line
    body embedded raw breaks the markdown bullet list. Escape characters
    that would otherwise corrupt formatting once dropped into a bullet."""
    first_line = text.splitlines()[0] if text else ""
    return _MD_SPECIAL_CHARS.sub(r"\\\1", first_line.strip())


def _parse_commit(commit: git.Commit, tag: str | None = None) -> ChangelogEntry:
    msg = _sanitize_message(commit.message)
    m = _CONVENTIONAL.match(msg)
    if m:
        kind_raw = m.group("kind").lower()
        valid = {"feat", "fix", "refactor", "chore", "docs", "test", "ci"}
        kind: Literal["feat","fix","refactor","chore","docs","test","ci","other"] = (
            kind_raw if kind_raw in valid else "other"
        )
        return ChangelogEntry(
            sha=commit.hexsha[:8],
            message=m.group("msg").strip(),
            author=str(commit.author),
            date=datetime.fromtimestamp(commit.committed_date),
            tag=tag,
            scope=m.group("scope"),
            breaking=bool(m.group("breaking")),
            kind=kind,
        )
    return ChangelogEntry(
        sha=commit.hexsha[:8],
        message=msg,
        author=str(commit.author),
        date=datetime.fromtimestamp(commit.committed_date),
        tag=tag,
    )


class CommitHistory:
    def __init__(self, repo_path: Path) -> None:
        self.repo_path = repo_path
        self._repo: git.Repo | None = None

    @property
    def repo(self) -> git.Repo:
        if self._repo is None:
            self._repo = git.Repo(self.repo_path)
        return self._repo

    async def tags(self) -> list[str]:
        def _get() -> list[str]:
            return [t.name for t in sorted(self.repo.tags, key=lambda t: t.commit.committed_date)]
        return await asyncio.to_thread(_get)

    async def previous_tag(self, tag: str) -> str | None:
        all_tags = await self.tags()
        try:
            idx = all_tags.index(tag)
            return all_tags[idx - 1] if idx > 0 else None
        except ValueError:
            return None

    async def log_range(self, from_ref: str | None, to_ref: str) -> list[ChangelogEntry]:
        def _get() -> list[ChangelogEntry]:
            rev = f"{from_ref}..{to_ref}" if from_ref else to_ref
            commits = list(self.repo.iter_commits(rev))
            return [_parse_commit(c, tag=to_ref) for c in commits]
        return await asyncio.to_thread(_get)

    async def author_commit_counts(self) -> list[tuple[str, str, int]]:
        """(name, email, commit count) per author across the full history,
        sorted descending. Author names are raw git identities — map them to
        real names via GLOSSARY.md if needed."""
        def _get() -> list[tuple[str, str, int]]:
            counts: dict[tuple[str, str], int] = {}
            for commit in self.repo.iter_commits():
                key = (commit.author.name or "", commit.author.email or "")
                counts[key] = counts.get(key, 0) + 1
            return sorted(
                ((name, email, count) for (name, email), count in counts.items()),
                key=lambda t: t[2], reverse=True,
            )
        return await asyncio.to_thread(_get)
