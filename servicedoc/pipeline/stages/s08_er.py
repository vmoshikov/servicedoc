import asyncio
import json
import logging
from typing import ClassVar

from jinja2 import Template

from servicedoc.ai.client import AIClient
from servicedoc.ai.glossary import glossary_system_block
from servicedoc.ai.prompts import ER_MIGRATION_SYSTEM, ER_MIGRATION_USER
from servicedoc.er.detector import GoGORMDetector, ORMDetector, PySQLAlchemyDetector, RawSQLDetector
from servicedoc.er.migrations import chunk_migrations, find_migration_files
from servicedoc.er.renderer import PlantUMLRenderer
from servicedoc.models.er import EREntity, ERRelation, SqlFunction
from servicedoc.models.pipeline import PipelineContext, StageResult
from servicedoc.pipeline.base import Stage

logger = logging.getLogger(__name__)

_EMPTY_DIAGRAM = "@startuml\n@enduml"
_FUNCTIONS_MARKER = "---FUNCTIONS---"


def _extract_plantuml(text: str) -> str | None:
    start = text.find("@startuml")
    end = text.rfind("@enduml")
    if start >= 0 and end > start:
        return text[start:end + len("@enduml")]
    return None


def _extract_functions(text: str) -> list[SqlFunction] | None:
    marker_idx = text.find(_FUNCTIONS_MARKER)
    tail = text[marker_idx + len(_FUNCTIONS_MARKER):] if marker_idx >= 0 else text
    start = tail.find("[")
    end = tail.rfind("]")
    if start < 0 or end < start:
        return None
    try:
        raw = json.loads(tail[start:end + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(raw, list):
        return None
    functions = []
    for item in raw:
        if isinstance(item, dict) and item.get("name"):
            functions.append(SqlFunction(
                name=item.get("name", ""),
                signature=item.get("signature", ""),
                returns=item.get("returns", ""),
                language=item.get("language", ""),
                description=item.get("description", ""),
            ))
    return functions


class ERDiagramStage(Stage):
    name: ClassVar[str] = "s08_er"
    required: ClassVar[bool] = False

    def __init__(self, ai_client: AIClient | None = None) -> None:
        self.ai_client = ai_client
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

    async def _build_from_migrations(
        self, ctx: PipelineContext, migration_files: list,
    ) -> tuple[str | None, list[SqlFunction]]:
        """One SQL migration file at a time won't fit the whole schema, and
        100+ files won't fit one AI call — so the diagram AND the SQL
        function registry are built incrementally together (one AI call per
        batch, not two): each batch gets both diagram-so-far and
        functions-so-far plus the next chunk of migrations, and returns
        both updated. Necessarily sequential (each step depends on the
        previous one's output)."""
        batches = chunk_migrations(migration_files)
        diagram = _EMPTY_DIAGRAM
        functions: list[SqlFunction] = []
        extra_system = glossary_system_block(ctx.glossary_text)
        system = ER_MIGRATION_SYSTEM + (f"\n\n{extra_system}" if extra_system else "")

        for i, batch in enumerate(batches):
            items = []
            for f in batch:
                try:
                    content = f.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    content = ""
                items.append({"filename": f.name, "content": content})

            functions_json = json.dumps([f.model_dump() for f in functions], ensure_ascii=False)
            user_prompt = Template(ER_MIGRATION_USER).render(
                current_diagram=diagram, current_functions_json=functions_json, batch=items,
            )
            try:
                response = await self.ai_client.complete(system, user_prompt)
            except Exception as exc:
                logger.warning("ER migration batch %d/%d failed: %s", i + 1, len(batches), exc)
                continue
            if response:
                diagram = _extract_plantuml(response) or diagram
                functions = _extract_functions(response) or functions
            logger.info("ER migration batch %d/%d: %d functions tracked", i + 1, len(batches), len(functions))

        return (diagram if diagram != _EMPTY_DIAGRAM else None), functions

    async def run(self, ctx: PipelineContext) -> StageResult:
        if ctx.local_repo_path and self.ai_client:
            migration_files = find_migration_files(ctx.local_repo_path)
            if migration_files:
                logger.info("Found %d SQL migration files, building ER diagram via AI", len(migration_files))
                diagram, functions = await self._build_from_migrations(ctx, migration_files)
                if diagram:
                    ctx.er_diagram = diagram
                    ctx.sql_functions = functions
                    logger.info(
                        "ER diagram built from %d migrations (%d SQL functions)",
                        len(migration_files), len(functions),
                    )
                    return StageResult(stage_name=self.name, success=True)
                logger.warning("AI ER migration build produced nothing, falling back to static detectors")

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
