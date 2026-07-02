"""Incremental manifest: stores symbol hashes → AI descriptions to avoid regen."""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MANIFEST_FILE = "symbol_manifest.json"


def _symbol_hash(file_path: Path, line_start: int, line_end: int, source: bytes) -> str:
    lines = source.split(b"\n")[line_start - 1:line_end]
    return hashlib.sha256(b"\n".join(lines)).hexdigest()[:16]


class SymbolManifest:
    """Persistent map of symbol_hash → ai_description for incremental AI enrichment."""

    def __init__(self, manifest_dir: Path) -> None:
        self._path = manifest_dir / MANIFEST_FILE
        self._data: dict[str, str] = self._load()

    def _load(self) -> dict[str, str]:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("Failed to load manifest: %s", exc)
        return {}

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, key: str) -> str | None:
        return self._data.get(key)

    def set(self, key: str, description: str) -> None:
        self._data[key] = description

    def make_key(self, file_path: Path, line_start: int, line_end: int, source: bytes) -> str:
        return _symbol_hash(file_path, line_start, line_end, source)
