import logging
from datetime import datetime
from typing import ClassVar

from servicedoc.ai.client import AIClient
from servicedoc.ai.prompts import (
    README_OVERVIEW_SYSTEM,
    README_OVERVIEW_USER,
    RELEASE_NOTES_SYSTEM,
    RELEASE_NOTES_USER,
)
from servicedoc.docs.renderer import MarkdownRenderer
from servicedoc.git.diff import DiffExtractor
from servicedoc.git.history import CommitHistory
from servicedoc.models.docs import ReleaseNote
from servicedoc.models.pipeline import PipelineContext, StageResult
from servicedoc.pipeline.base import Stage

logger = logging.getLogger(__name__)


class DocumentationStage(Stage):
    name: ClassVar[str] = "s09_docs"
    required: ClassVar[bool] = True

    def __init__(self, ai_client: AIClient | None = None) -> None:
        self.ai_client = ai_client
        self.renderer = MarkdownRenderer()

    async def run(self, ctx: PipelineContext) -> StageResult:
        if not ctx.local_repo_path:
            return StageResult(stage_name=self.name, success=False, errors=["No repo path"])

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
                changed_symbol_names = [
                    s.name for s in ctx.public_symbols
                    if str(s.file_path.relative_to(ctx.local_repo_path)) in diff_map
                ]

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
                        service_name=ctx.local_repo_path.name,
                        changed_symbols=ctx.public_symbols[:10],
                        changelog_entries=tag_entries[:20],
                        stats=stats,
                    )
                    try:
                        ai_summary = await self.ai_client.complete(RELEASE_NOTES_SYSTEM, user_prompt)
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

        overview = await self._build_overview(ctx, tags)

        docs = await self.renderer.render_all(ctx, release_notes=release_notes, overview=overview)
        logger.info("Generated %d documentation files", len(docs))
        return StageResult(stage_name=self.name, success=True)

    async def _build_overview(self, ctx: PipelineContext, tags: list[str]) -> str | None:
        """Summarize the public API surface + latest changelog into a short
        README overview, grounded in ctx.public_symbols / ctx.proto_services /
        ctx.git_history — no separate parse of the rendered API.md/CHANGELOG.md."""
        if not self.ai_client:
            return None

        public_symbols = ctx.public_symbols
        if not public_symbols and not ctx.proto_services:
            return None

        api_summary: dict[str, int] = {}
        for sym in public_symbols:
            api_summary[sym.kind] = api_summary.get(sym.kind, 0) + 1

        top_dirs: list[str] = []
        for sym in public_symbols:
            try:
                rel = sym.file_path.relative_to(ctx.local_repo_path) if ctx.local_repo_path else sym.file_path
            except ValueError:
                rel = sym.file_path
            parent = str(rel.parent).replace("\\", "/")
            if parent not in top_dirs:
                top_dirs.append(parent)
        top_dirs = top_dirs[:15]

        recent_changes: list[str] = []
        if tags:
            latest_tag = tags[-1]
            recent_changes = [
                e.message for e in ctx.git_history
                if e.tag == latest_tag and e.kind in ("feat", "fix")
            ][:15]

        from jinja2 import Template
        user_prompt = Template(README_OVERVIEW_USER).render(
            service_name=ctx.local_repo_path.name if ctx.local_repo_path else "service",
            api_summary=api_summary,
            top_dirs=top_dirs,
            proto_service_names=[s.name for s in ctx.proto_services],
            recent_changes=recent_changes,
        )
        try:
            return await self.ai_client.complete(README_OVERVIEW_SYSTEM, user_prompt)
        except Exception as exc:
            logger.warning("AI README overview failed: %s", exc)
            return None
