import asyncio
import logging
from typing import ClassVar

from servicedoc.ai.client import AIClient
from servicedoc.docs.regenerate_markers import scan_regenerate_markers
from servicedoc.models.pipeline import PipelineContext, StageResult
from servicedoc.pipeline.base import Stage
from servicedoc.utils.manifest import SymbolManifest

logger = logging.getLogger(__name__)


def _chunk(lst: list, size: int) -> list[list]:
    return [lst[i: i + size] for i in range(0, len(lst), size)]


class AIEnrichmentStage(Stage):
    name: ClassVar[str] = "s06_ai_enrich"
    required: ClassVar[bool] = False

    def __init__(self, client: AIClient, batch_size: int = 10, max_concurrent: int = 3) -> None:
        self.client = client
        self.batch_size = batch_size
        self.semaphore = asyncio.Semaphore(max_concurrent)

    async def run(self, ctx: PipelineContext) -> StageResult:
        # symbols marked with `<!-- @ai:regenerate -->` in a previously
        # generated .md file get their AI description force-refreshed,
        # bypassing the manifest cache (comment-authored symbols are left
        # alone — a hand-written doc comment always wins over ai_description).
        forced_names = scan_regenerate_markers(ctx.output_dir)
        if forced_names:
            for sym in ctx.symbols:
                if sym.name in forced_names and sym.comment is None:
                    sym.needs_ai = True

        needs_ai = [s for s in ctx.symbols if s.needs_ai]
        if not needs_ai:
            return StageResult(stage_name=self.name, success=True)

        manifest = SymbolManifest(ctx.work_dir)

        # load source files once
        source_map: dict = {}
        for sym in needs_ai:
            if sym.file_path not in source_map:
                try:
                    source_map[sym.file_path] = sym.file_path.read_bytes()
                except Exception:
                    source_map[sym.file_path] = b""

        # split into cached vs fresh
        truly_needs_ai = []
        cached_count = 0
        for sym in needs_ai:
            src = source_map.get(sym.file_path, b"")
            key = manifest.make_key(sym.file_path, sym.line_start, sym.line_end, src)
            cached = None if sym.name in forced_names else manifest.get(key)
            if cached:
                sym.ai_description = cached
                sym.needs_ai = False
                cached_count += 1
            else:
                truly_needs_ai.append((sym, key))

        logger.info(
            "AI enrichment: %d from cache, %d need fresh AI call",
            cached_count, len(truly_needs_ai),
        )

        if not truly_needs_ai:
            return StageResult(stage_name=self.name, success=True)

        fresh_symbols = [sym for sym, _ in truly_needs_ai]
        fresh_keys = [key for _, key in truly_needs_ai]
        batches = list(zip(_chunk(fresh_symbols, self.batch_size), _chunk(fresh_keys, self.batch_size)))
        enriched = 0
        errors: list[str] = []

        async def process_batch(sym_batch: list, key_batch: list) -> None:
            nonlocal enriched
            async with self.semaphore:
                descriptions = await self.client.describe_batch(sym_batch, source_map)
                for sym, key, desc in zip(sym_batch, key_batch, descriptions):
                    if desc:
                        sym.ai_description = desc
                        manifest.set(key, desc)
                        enriched += 1

        tasks = [process_batch(sb, kb) for sb, kb in batches]
        await asyncio.gather(*tasks, return_exceptions=True)

        manifest.save()
        logger.info("AI enriched %d fresh symbols (%d total)", enriched, enriched + cached_count)
        return StageResult(stage_name=self.name, success=True, errors=errors)
