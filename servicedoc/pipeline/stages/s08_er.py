import asyncio
import logging
from typing import ClassVar

from servicedoc.er.detector import GoGORMDetector, ORMDetector, PySQLAlchemyDetector, RawSQLDetector
from servicedoc.er.renderer import PlantUMLRenderer
from servicedoc.models.er import EREntity, ERRelation
from servicedoc.models.pipeline import PipelineContext, StageResult
from servicedoc.pipeline.base import Stage

logger = logging.getLogger(__name__)


class ERDiagramStage(Stage):
    name: ClassVar[str] = "s08_er"
    required: ClassVar[bool] = False

    def __init__(self) -> None:
        self.go_detector = GoGORMDetector()
        self.py_detector = PySQLAlchemyDetector()
        self.sql_detector = RawSQLDetector()
        self.renderer = PlantUMLRenderer()

    def _detectors_for(self, path) -> list[ORMDetector]:
        if path.suffix == ".go":
            return [self.go_detector]
        if path.suffix == ".py":
            return [self.py_detector, self.sql_detector]
        return []

    async def run(self, ctx: PipelineContext) -> StageResult:
        entities: list[EREntity] = []
        relations: list[ERRelation] = []

        async def process(path):
            try:
                source = await asyncio.to_thread(path.read_bytes)
                for detector in self._detectors_for(path):
                    ents, rels = await asyncio.to_thread(detector.detect, source, path)
                    entities.extend(ents)
                    relations.extend(rels)
            except Exception as exc:
                logger.debug("ER detection error %s: %s", path, exc)

        await asyncio.gather(*[process(f) for f in ctx.all_source_files])

        # deduplicate entities by name
        seen_entities: dict[str, EREntity] = {}
        for ent in entities:
            if ent.name not in seen_entities:
                seen_entities[ent.name] = ent
        ctx.er_entities = list(seen_entities.values())
        ctx.er_relations = relations

        if ctx.er_entities:
            ctx.er_diagram = self.renderer.render(ctx.er_entities, ctx.er_relations)
            logger.info("ER diagram: %d entities, %d relations", len(ctx.er_entities), len(ctx.er_relations))
        else:
            logger.info("No DB entities detected")

        return StageResult(stage_name=self.name, success=True)
