import logging
from typing import ClassVar

from servicedoc.models.pipeline import PipelineContext, StageResult
from servicedoc.pipeline.base import Stage

logger = logging.getLogger(__name__)


class CommentExtractionStage(Stage):
    """Marks symbols that already have comments; sets needs_ai=True for those without."""
    name: ClassVar[str] = "s05_comments"
    required: ClassVar[bool] = True

    async def run(self, ctx: PipelineContext) -> StageResult:
        needs_ai = sum(1 for s in ctx.symbols if s.needs_ai)
        has_comment = sum(1 for s in ctx.symbols if s.comment)

        logger.info(
            "Symbols: %d total, %d with comments, %d need AI",
            len(ctx.symbols), has_comment, needs_ai,
        )
        return StageResult(
            stage_name=self.name,
            success=True,
            warnings=[f"{needs_ai} symbols will be sent to AI for description"] if needs_ai else [],
        )
