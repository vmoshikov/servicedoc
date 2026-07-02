from abc import ABC, abstractmethod
from typing import ClassVar

from servicedoc.models.pipeline import PipelineContext, StageResult


class Stage(ABC):
    name: ClassVar[str]
    required: ClassVar[bool] = True

    @abstractmethod
    async def run(self, ctx: PipelineContext) -> StageResult:
        ...

    async def validate_input(self, ctx: PipelineContext) -> bool:
        return True
