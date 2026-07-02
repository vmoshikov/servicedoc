"""Generate clickable source links for GitHub / GitLab / generic git hosts."""
from __future__ import annotations

import re
from pathlib import Path


def _normalize_url(url: str) -> str:
    """Strip .git suffix and trailing slash."""
    return url.rstrip("/").removesuffix(".git")


def detect_host(url: str) -> str:
    if "github.com" in url:
        return "github"
    if "gitlab" in url:
        return "gitlab"
    return "generic"


def source_link(
    repo_url: str,
    branch: str,
    file_path: Path,
    repo_root: Path,
    line_start: int,
    line_end: int | None = None,
) -> str:
    """Return a clickable URL pointing to the specific line(s) in the repo."""
    base = _normalize_url(repo_url)
    try:
        rel = file_path.relative_to(repo_root)
    except ValueError:
        return str(file_path)

    host = detect_host(repo_url)
    path_str = str(rel).replace("\\", "/")

    if host == "github":
        anchor = f"#L{line_start}" + (f"-L{line_end}" if line_end and line_end != line_start else "")
        return f"{base}/blob/{branch}/{path_str}{anchor}"
    if host == "gitlab":
        anchor = f"#L{line_start}" + (f"-{line_end}" if line_end and line_end != line_start else "")
        return f"{base}/-/blob/{branch}/{path_str}{anchor}"
    # generic: best-effort
    return f"{base}/blob/{branch}/{path_str}#L{line_start}"


def make_source_ref(
    repo_url: str,
    branch: str,
    file_path: Path,
    repo_root: Path,
    line_start: int,
    line_end: int | None = None,
) -> str:
    """Return Markdown link: `path/to/file.go:42` pointing to the line."""
    url = source_link(repo_url, branch, file_path, repo_root, line_start, line_end)
    try:
        rel = str(file_path.relative_to(repo_root)).replace("\\", "/")
    except ValueError:
        rel = str(file_path)
    label = f"{rel}:{line_start}"
    return f"[`{label}`]({url})"
