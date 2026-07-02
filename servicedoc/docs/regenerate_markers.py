from __future__ import annotations

import re
from pathlib import Path

_SECTION_WITH_ID_RE = re.compile(r'<!--\s*@ai:section\b.*?\bid="([^"]+)"')
_SECTION_OPEN_RE = re.compile(r"<!--\s*@ai:section\b")
_FIELD_OPEN_RE = re.compile(r"<!--\s*@ai:field\b")
_END_RE = re.compile(r"<!--\s*@ai:end\s*-->")
_REGENERATE_RE = re.compile(r"<!--\s*@ai:regenerate\s*-->")


def scan_regenerate_markers(output_dir: Path) -> set[str]:
    """Scan already-generated .md files for `<!-- @ai:regenerate -->` markers.

    Returns the set of symbol names (taken from the id="..." of the nearest
    enclosing `@ai:section`) whose AI description should be force-refreshed
    on the next run, bypassing the manifest cache.
    """
    marked: set[str] = set()
    if not output_dir.exists():
        return marked

    for md_file in output_dir.rglob("*.md"):
        stack: list[str | None] = []
        try:
            lines = md_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            if _REGENERATE_RE.search(line):
                for entry in reversed(stack):
                    if entry is not None:
                        marked.add(entry)
                        break
                continue
            if m := _SECTION_WITH_ID_RE.search(line):
                stack.append(m.group(1))
                continue
            if _SECTION_OPEN_RE.search(line) or _FIELD_OPEN_RE.search(line):
                stack.append(None)
                continue
            if _END_RE.search(line) and stack:
                stack.pop()

    return marked
