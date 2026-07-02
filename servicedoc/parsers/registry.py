from pathlib import Path

from .base import LanguageParser


class ParserRegistry:
    def __init__(self) -> None:
        self._parsers: dict[str, LanguageParser] = {}

    def register(self, parser: LanguageParser) -> None:
        for ext in parser.extensions:
            self._parsers[ext] = parser

    def get(self, path: Path) -> LanguageParser | None:
        return self._parsers.get(path.suffix)

    def get_by_language(self, language: str) -> LanguageParser | None:
        for parser in self._parsers.values():
            if parser.language_name == language:
                return parser
        return None

    @classmethod
    def default(cls) -> "ParserRegistry":
        from servicedoc.parsers.go.parser import GoParser
        from servicedoc.parsers.python.parser import PythonParser

        registry = cls()
        registry.register(GoParser())
        registry.register(PythonParser())
        return registry
