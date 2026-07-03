from __future__ import annotations

import re
from pathlib import Path

_LEADING_NUM_RE = re.compile(r"^0*(\d+)")


def find_migration_files(root: Path) -> list[Path]:
    """`*.up.sql` files (golang-migrate convention), sorted by their leading
    numeric prefix (e.g. "2_x.up.sql" before "10_y.up.sql" — lexicographic
    sort would get that backwards). `.down.sql` files are rollback SQL and
    are intentionally excluded — we want the forward-applied schema."""
    files = list(root.rglob("*.up.sql"))

    def _sort_key(p: Path) -> tuple[int, str]:
        m = _LEADING_NUM_RE.match(p.name)
        return (int(m.group(1)) if m else 0, p.name)

    return sorted(files, key=_sort_key)


def chunk_migrations(files: list[Path], max_chars: int = 6000) -> list[list[Path]]:
    """Group migration files into batches bounded by total character count
    (not just file count) — a handful of huge migrations could otherwise
    blow the AI context budget as easily as 100 tiny ones."""
    batches: list[list[Path]] = []
    current: list[Path] = []
    current_len = 0
    for f in files:
        try:
            size = f.stat().st_size
        except OSError:
            size = 0
        if current and current_len + size > max_chars:
            batches.append(current)
            current = []
            current_len = 0
        current.append(f)
        current_len += size
    if current:
        batches.append(current)
    return batches
