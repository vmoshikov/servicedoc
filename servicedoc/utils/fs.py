import asyncio
from pathlib import Path
from typing import AsyncIterator

GO_EXTENSIONS = frozenset({".go"})
PYTHON_EXTENSIONS = frozenset({".py"})
SOURCE_EXTENSIONS = GO_EXTENSIONS | PYTHON_EXTENSIONS
TEST_PATTERNS = frozenset({"_test.go", "test_", "_test.py"})
SKIP_DIRS = frozenset({".git", "vendor", "node_modules", "__pycache__", ".venv", "venv"})


async def walk_source_files(root: Path, extensions: frozenset[str] | None = None) -> AsyncIterator[Path]:
    exts = extensions or SOURCE_EXTENSIONS

    def _walk() -> list[Path]:
        result = []
        for path in root.rglob("*"):
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            if path.suffix in exts and path.is_file():
                result.append(path)
        return result

    files = await asyncio.to_thread(_walk)
    for f in files:
        yield f


def detect_language(files: list[Path]) -> str:
    has_go = any(f.suffix == ".go" for f in files)
    has_py = any(f.suffix == ".py" for f in files)
    if has_go and has_py:
        return "mixed"
    if has_go:
        return "go"
    if has_py:
        return "python"
    return "unknown"


def is_test_file(path: Path) -> bool:
    name = path.name
    return name.endswith("_test.go") or name.startswith("test_") or name.endswith("_test.py")
