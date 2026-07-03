import asyncio
import logging
from pathlib import Path
from typing import ClassVar

from servicedoc.models.pipeline import PipelineContext, StageResult
from servicedoc.models.symbols import Symbol
from servicedoc.parsers.registry import ParserRegistry
from servicedoc.pipeline.base import Stage
from servicedoc.utils.fs import SKIP_DIRS, is_generated_file

logger = logging.getLogger(__name__)


class CodeParsingStage(Stage):
    name: ClassVar[str] = "s03_parse"
    required: ClassVar[bool] = True

    def __init__(self, registry: ParserRegistry, max_concurrent: int = 8) -> None:
        self.registry = registry
        self.semaphore = asyncio.Semaphore(max_concurrent)

    async def _parse_file(self, path, errors: list[str]) -> list[Symbol]:
        parser = self.registry.get(path)
        if not parser:
            return []
        async with self.semaphore:
            try:
                return await parser.parse_file(path)
            except Exception as exc:
                errors.append(f"{path}: {exc}")
                logger.debug("Parse error %s: %s", path, exc)
                return []

    async def _scan_generated_structs(self, ctx: PipelineContext, errors: list[str]) -> list[Symbol]:
        """Parse generated files (.pb.go, ...) for struct shapes only.

        These are excluded from ctx.symbols entirely (never shown in docs),
        but a vendored request/response type may have no accompanying .proto
        in this repo — this is the only source left to resolve its JSON
        example shape.
        """
        if not ctx.local_repo_path:
            return []

        def _walk() -> list[Path]:
            result = []
            for path in ctx.local_repo_path.rglob("*.go"):
                if any(part in SKIP_DIRS for part in path.parts):
                    continue
                if is_generated_file(path) and path.is_file():
                    result.append(path)
            return result

        generated_files = await asyncio.to_thread(_walk)
        tasks = [self._parse_file(f, errors) for f in generated_files]
        results = await asyncio.gather(*tasks)

        symbols: list[Symbol] = []
        for result in results:
            symbols.extend(s for s in result if s.kind == "struct")
        return symbols

    async def run(self, ctx: PipelineContext) -> StageResult:
        errors: list[str] = []
        all_files = list(ctx.all_source_files)

        # also add dep files
        for dep in ctx.external_deps:
            all_files.extend(dep.analyzed_files)

        tasks = [self._parse_file(f, errors) for f in all_files]
        results = await asyncio.gather(*tasks)

        symbols: list[Symbol] = []
        for result in results:
            symbols.extend(result)

        ctx.symbols = symbols
        ctx.generated_symbols = await self._scan_generated_structs(ctx, errors)
        logger.info(
            "Parsed %d symbols from %d files (+%d generated-only structs)",
            len(symbols), len(all_files), len(ctx.generated_symbols),
        )
        return StageResult(
            stage_name=self.name,
            success=True,
            errors=errors,
            warnings=[f"Parse errors: {len(errors)}"] if errors else [],
        )
