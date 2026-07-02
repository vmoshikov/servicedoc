import asyncio
import logging
from typing import ClassVar

from servicedoc.models.pipeline import PipelineContext, StageResult
from servicedoc.models.symbols import Symbol
from servicedoc.parsers.registry import ParserRegistry
from servicedoc.pipeline.base import Stage

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
        logger.info("Parsed %d symbols from %d files", len(symbols), len(all_files))
        return StageResult(
            stage_name=self.name,
            success=True,
            errors=errors,
            warnings=[f"Parse errors: {len(errors)}"] if errors else [],
        )
