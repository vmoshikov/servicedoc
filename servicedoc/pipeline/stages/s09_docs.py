import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import ClassVar

from servicedoc.ai.client import AIClient
from servicedoc.ai.glossary import glossary_system_block
from servicedoc.ai.prompts import (
    ER_DESCRIPTION_SYSTEM,
    ER_DESCRIPTION_USER,
    PROVIDER_OVERVIEW_SYSTEM,
    PROVIDER_OVERVIEW_USER,
    README_OVERVIEW_SYSTEM,
    README_OVERVIEW_USER,
    RELEASE_NOTES_SYSTEM,
    RELEASE_NOTES_USER,
)
from servicedoc.docs.renderer import (
    _FUNCS_KINDS,
    _STRUCTS_KINDS,
    _categorize_dirs,
    _group_proto_by_visibility,
    _group_symbols_by_dir,
    _relevant_proto_objects,
    _service_name,
    MarkdownRenderer,
)
from servicedoc.git.diff import DiffExtractor, touched_line_ranges
from servicedoc.git.history import CommitHistory
from servicedoc.models.docs import ReleaseNote
from servicedoc.models.pipeline import PipelineContext, StageResult
from servicedoc.pipeline.base import Stage

logger = logging.getLogger(__name__)


def _chunk(lst: list, size: int) -> list[list]:
    return [lst[i: i + size] for i in range(0, len(lst), size)]


class DocumentationStage(Stage):
    name: ClassVar[str] = "s09_docs"
    required: ClassVar[bool] = True

    def __init__(self, ai_client: AIClient | None = None, plantuml_server_url: str | None = None) -> None:
        self.ai_client = ai_client
        self.renderer = MarkdownRenderer(**({"plantuml_server_url": plantuml_server_url} if plantuml_server_url else {}))

    async def run(self, ctx: PipelineContext) -> StageResult:
        if not ctx.local_repo_path:
            return StageResult(stage_name=self.name, success=False, errors=["No repo path"])

        service_name = _service_name(ctx)
        history = CommitHistory(ctx.local_repo_path)
        diff_extractor = DiffExtractor(ctx.local_repo_path)

        tags = await history.tags()
        ctx.git_tags = tags

        for i, tag in enumerate(tags):
            prev_tag = tags[i - 1] if i > 0 else None
            entries = await history.log_range(prev_tag, tag)
            for entry in entries:
                entry.tag = tag
            ctx.git_history.extend(entries)

        rn_dir = ctx.output_dir / "RELEASE_NOTES"
        rn_dir.mkdir(parents=True, exist_ok=True)

        extra_system = glossary_system_block(ctx.glossary_text)

        release_notes: list[ReleaseNote] = []
        for i, tag in enumerate(tags):
            prev_tag = tags[i - 1] if i > 0 else None
            rn_file = rn_dir / f"{tag}.md"

            # skip tags that already have release notes (incremental)
            if rn_file.exists():
                logger.info("Release notes for %s already exist, skipping AI regen", tag)
                # still build ReleaseNote object for changelog consistency
                release_notes.append(ReleaseNote(
                    tag=tag,
                    prev_tag=prev_tag,
                    date=datetime.now(),
                    changelog_entries=[e for e in ctx.git_history if e.tag == tag],
                ))
                continue

            try:
                tag_entries = [e for e in ctx.git_history if e.tag == tag]
                stats = await diff_extractor.stats(prev_tag, tag)
                diff_map = await diff_extractor.get_diff(prev_tag, tag)
                # match by touched line ranges, not just "file appears in the
                # diff" — otherwise every public symbol in a file counts as
                # "changed" even if only one unrelated function in it moved.
                changed_symbol_names = []
                for s in ctx.public_symbols:
                    try:
                        rel = str(s.file_path.relative_to(ctx.local_repo_path))
                    except ValueError:
                        continue
                    patch_text = diff_map.get(rel)
                    if not patch_text:
                        continue
                    ranges = touched_line_ranges(patch_text)
                    if any(s.line_start <= r_end and s.line_end >= r_start for r_start, r_end in ranges):
                        changed_symbol_names.append(s.name)

                try:
                    import git
                    repo = git.Repo(ctx.local_repo_path)
                    tag_commit = repo.tags[i].commit
                    note_date = datetime.fromtimestamp(tag_commit.committed_date)
                except Exception:
                    note_date = datetime.now()

                ai_summary: str | None = None
                if self.ai_client and tag_entries:
                    from jinja2 import Template
                    user_prompt = Template(RELEASE_NOTES_USER).render(
                        tag=tag,
                        service_name=service_name,
                        changed_symbols=ctx.public_symbols[:10],
                        changelog_entries=tag_entries[:20],
                        stats=stats,
                    )
                    system = RELEASE_NOTES_SYSTEM + (f"\n\n{extra_system}" if extra_system else "")
                    try:
                        ai_summary = await self.ai_client.complete(system, user_prompt)
                    except Exception as exc:
                        logger.warning("AI release notes failed for %s: %s", tag, exc)

                release_notes.append(ReleaseNote(
                    tag=tag,
                    prev_tag=prev_tag,
                    date=note_date,
                    ai_summary=ai_summary,
                    changelog_entries=tag_entries,
                    changed_files_count=stats.get("files", 0),
                    added_lines=stats.get("added", 0),
                    removed_lines=stats.get("removed", 0),
                    changed_symbols=changed_symbol_names,
                ))
            except Exception as exc:
                logger.warning("Release notes error for tag %s: %s", tag, exc)

        await self._enrich_proto_descriptions(ctx, service_name, extra_system)
        overview = await self._build_overview(ctx, tags, service_name, extra_system)
        er_description = await self._describe_er(ctx, service_name, extra_system)
        provider_overview = await self._describe_providers(ctx, service_name, extra_system)
        contributors = await history.author_commit_counts()

        docs = await self.renderer.render_all(
            ctx, release_notes=release_notes, overview=overview, contributors=contributors,
            er_description=er_description, provider_overview=provider_overview,
        )
        logger.info("Generated %d documentation files", len(docs))
        return StageResult(stage_name=self.name, success=True)

    async def _enrich_proto_descriptions(
        self, ctx: PipelineContext, service_name: str, extra_system: str | None,
    ) -> None:
        """AI-describe gRPC services/RPCs/messages that have no leading proto
        comment — scoped to the relevant subset only (same filter as API.md),
        so a shared/vendored proto repo doesn't burn AI calls on other
        services' unrelated contracts."""
        if not self.ai_client:
            return

        relevant_services, relevant_messages = _relevant_proto_objects(ctx, service_name)

        source_cache: dict[Path, bytes] = {}

        def _read(path: Path) -> bytes:
            if path not in source_cache:
                try:
                    source_cache[path] = path.read_bytes()
                except OSError:
                    source_cache[path] = b""
            return source_cache[path]

        def _slice(path: Path, line_start: int, line_end: int) -> str:
            lines = _read(path).split(b"\n")
            return b"\n".join(lines[line_start - 1:line_end]).decode("utf-8", errors="replace")

        items: list[dict] = []
        refs: list = []

        for svc in relevant_services:
            if svc.needs_ai and svc.line_start and svc.line_end:
                items.append({
                    "name": svc.name, "kind": "grpc_service", "file_path": str(svc.file_path),
                    "line_start": svc.line_start, "line_end": svc.line_end,
                    "code_block": _slice(svc.file_path, svc.line_start, svc.line_end),
                })
                refs.append(svc)
            for method in svc.methods:
                if method.needs_ai and method.line:
                    items.append({
                        "name": method.name, "kind": "rpc_method", "file_path": str(svc.file_path),
                        "line_start": method.line, "line_end": method.line,
                        "code_block": _slice(svc.file_path, method.line, method.line),
                    })
                    refs.append(method)

        for msg in relevant_messages:
            if msg.needs_ai and msg.file_path and msg.line_start and msg.line_end:
                items.append({
                    "name": msg.name, "kind": "proto_message", "file_path": str(msg.file_path),
                    "line_start": msg.line_start, "line_end": msg.line_end,
                    "code_block": _slice(msg.file_path, msg.line_start, msg.line_end),
                })
                refs.append(msg)

        if not items:
            return

        item_batches = _chunk(items, 10)
        ref_batches = _chunk(refs, 10)

        async def process(item_batch: list, ref_batch: list) -> None:
            try:
                descriptions = await self.ai_client.describe_items_raw(item_batch, extra_system=extra_system)
            except Exception as exc:
                logger.warning("AI proto describe failed: %s", exc)
                return
            for ref, desc in zip(ref_batch, descriptions):
                if desc:
                    ref.ai_description = desc

        await asyncio.gather(*(process(ib, rb) for ib, rb in zip(item_batches, ref_batches)))

    async def _build_overview(
        self, ctx: PipelineContext, tags: list[str], service_name: str, extra_system: str | None,
    ) -> str | None:
        """Summarize the API.md / FUNCTIONS.md / STRUCTURES.md navigation
        (same grouping shown to the reader) + optional FOR_AI.md into a short
        README overview."""
        if not self.ai_client:
            return None

        public_symbols = ctx.public_symbols
        if not public_symbols and not ctx.proto_services:
            return None

        repo_root = ctx.local_repo_path or Path("/")

        relevant_services, relevant_messages = _relevant_proto_objects(ctx, service_name)
        proto_visibility_groups = _group_proto_by_visibility(relevant_services, relevant_messages)
        proto_groups = {
            group: [s.name for s in content["services"]] + [m.name for m in content["messages"]]
            for group, content in proto_visibility_groups.items()
        }

        func_symbols = [s for s in public_symbols if s.kind in _FUNCS_KINDS]
        struct_symbols = [s for s in public_symbols if s.kind in _STRUCTS_KINDS]
        functions_nav = _categorize_dirs(list(_group_symbols_by_dir(func_symbols, repo_root).keys()))
        structures_nav = _categorize_dirs(list(_group_symbols_by_dir(struct_symbols, repo_root).keys()))

        recent_changes: list[str] = []
        if tags:
            latest_tag = tags[-1]
            recent_changes = [
                e.message for e in ctx.git_history
                if e.tag == latest_tag and e.kind in ("feat", "fix")
            ][:15]

        from jinja2 import Template
        user_prompt = Template(README_OVERVIEW_USER).render(
            service_name=service_name,
            proto_groups=proto_groups,
            functions_nav=functions_nav,
            structures_nav=structures_nav,
            recent_changes=recent_changes,
            for_ai_text=ctx.for_ai_text,
        )
        system = README_OVERVIEW_SYSTEM + (f"\n\n{extra_system}" if extra_system else "")
        try:
            return await self.ai_client.complete(system, user_prompt)
        except Exception as exc:
            logger.warning("AI README overview failed: %s", exc)
            return None

    async def _describe_er(
        self, ctx: PipelineContext, service_name: str, extra_system: str | None,
    ) -> str | None:
        """Short, neutral technical description of the ER diagram — no
        quality judgments, just what's actually there (entity count,
        relation patterns, notable structural traits)."""
        if not self.ai_client or not ctx.er_diagram:
            return None
        from jinja2 import Template
        user_prompt = Template(ER_DESCRIPTION_USER).render(
            service_name=service_name,
            diagram=ctx.er_diagram,
            sql_functions=[f.name for f in ctx.sql_functions],
        )
        system = ER_DESCRIPTION_SYSTEM + (f"\n\n{extra_system}" if extra_system else "")
        try:
            return await self.ai_client.complete(system, user_prompt)
        except Exception as exc:
            logger.warning("AI ER description failed: %s", exc)
            return None

    async def _describe_providers(
        self, ctx: PipelineContext, service_name: str, extra_system: str | None,
    ) -> str | None:
        """Short description of what external systems/libraries the
        service's provider/ wrappers integrate with."""
        if not self.ai_client or not ctx.provider_names:
            return None
        from jinja2 import Template
        user_prompt = Template(PROVIDER_OVERVIEW_USER).render(
            service_name=service_name, provider_names=ctx.provider_names,
        )
        system = PROVIDER_OVERVIEW_SYSTEM + (f"\n\n{extra_system}" if extra_system else "")
        try:
            return await self.ai_client.complete(system, user_prompt)
        except Exception as exc:
            logger.warning("AI provider overview failed: %s", exc)
            return None
