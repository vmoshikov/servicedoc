import logging
from typing import ClassVar

from servicedoc.models.pipeline import PipelineContext, StageResult
from servicedoc.pipeline.base import Stage
from servicedoc.proto.parser import ProtoFileParser

logger = logging.getLogger(__name__)


class ProtoParsingStage(Stage):
    name: ClassVar[str] = "s04_proto"
    required: ClassVar[bool] = False

    async def run(self, ctx: PipelineContext) -> StageResult:
        if not ctx.local_repo_path:
            return StageResult(stage_name=self.name, success=False, errors=["No repo path"])

        proto_files = list(ctx.local_repo_path.rglob("*.proto"))
        if not proto_files:
            logger.info("No .proto files found")
            return StageResult(stage_name=self.name, success=True, warnings=["No .proto files found"])

        parser = ProtoFileParser()
        errors: list[str] = []
        for proto_file in proto_files:
            try:
                services, messages = parser.parse(proto_file)
                ctx.proto_services.extend(services)
                ctx.proto_messages.extend(messages)
            except Exception as exc:
                errors.append(f"{proto_file}: {exc}")
                logger.warning("Proto parse error %s: %s", proto_file, exc)

        logger.info("Parsed %d proto services from %d files", len(ctx.proto_services), len(proto_files))
        return StageResult(stage_name=self.name, success=True, errors=errors)
