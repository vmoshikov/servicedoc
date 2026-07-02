from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

from servicedoc.models.symbols import Symbol


class LanguageParser(ABC):
    language_name: ClassVar[str]
    extensions: ClassVar[frozenset[str]]

    @abstractmethod
    async def parse_file(self, path: Path) -> list[Symbol]:
        ...

    def is_test_file(self, path: Path) -> bool:
        name = path.name
        return name.endswith("_test.go") or name.startswith("test_") or name.endswith("_test.py")

    async def list_exported_names(self, path: Path) -> dict[str, Path]:
        """Lightweight scan: returns {exported_name: file_path}."""
        symbols = await self.parse_file(path)
        return {s.name: path for s in symbols if s.is_public}
