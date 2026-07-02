from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from servicedoc.docs.changelog import deduplicate, group_entries
from servicedoc.docs.json_example import TypeRegistry
from servicedoc.models.docs import DocOutput, ReleaseNote
from servicedoc.models.pipeline import PipelineContext
from servicedoc.models.symbols import Symbol, TypeRef
from servicedoc.utils.source_links import make_source_ref

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"


def _service_name(ctx: PipelineContext) -> str:
    url = ctx.repo_config.url
    if "@" in url:
        url = url.rsplit("@", 1)[0]
    return url.rstrip("/").split("/")[-1].removesuffix(".git")


def _group_symbols_by_dir(
    symbols: list[Symbol], repo_root: Path
) -> dict[str, list[Symbol]]:
    """Group symbols by containing directory (full relative path), sorted alpha."""
    groups: dict[str, list[Symbol]] = defaultdict(list)
    for sym in symbols:
        try:
            rel = sym.file_path.relative_to(repo_root)
        except ValueError:
            rel = sym.file_path
        parent = str(rel.parent).replace("\\", "/")
        section = "." if parent == "." else parent
        groups[section].append(sym)
    return {
        k: sorted(v, key=lambda s: s.name.lower())
        for k, v in sorted(groups.items())
    }


def _make_anchor(text: str) -> str:
    import re
    return re.sub(r"[^\w\- ]", "", text.lower()).replace(" ", "-")


def _dir_to_file_path(dir_name: str) -> str:
    """Convert dir key to relative file path under api/. '.' → api/root.md"""
    if dir_name == ".":
        return "api/root.md"
    return f"api/{dir_name}.md"


def _back_link(file_path: str) -> str:
    """Relative link back to API.md from a nested api/ file."""
    depth = file_path.count("/")
    return "../" * depth + "API.md"


_NAV_CATEGORY_ORDER = ["core", "app", "entity", "usecase", "provider", "controller"]
_NAV_OTHER_LABEL = "Прочее"


def _categorize_dirs(dir_names: list[str]) -> dict[str, list[str]]:
    """Group directory names into architecture-layer buckets by matching any
    path segment against the known category names; unmatched dirs go last
    under _NAV_OTHER_LABEL."""
    categories = {name: [] for name in _NAV_CATEGORY_ORDER}
    categories[_NAV_OTHER_LABEL] = []
    for dir_name in dir_names:
        parts = dir_name.split("/")
        matched = next((c for c in _NAV_CATEGORY_ORDER if c in parts), None)
        categories[(matched or _NAV_OTHER_LABEL)].append(dir_name)
    return {k: sorted(v) for k, v in categories.items() if v}


class MarkdownRenderer:
    def __init__(self) -> None:
        self.env = Environment(
            loader=FileSystemLoader(str(TEMPLATES_DIR)),
            autoescape=select_autoescape([]),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.env.globals["make_source_ref"] = make_source_ref

    def _render(self, template_name: str, **kwargs: object) -> str:
        return self.env.get_template(template_name).render(**kwargs)

    def _set_json_example_global(self, ctx: PipelineContext) -> None:
        registry = TypeRegistry(ctx)

        def json_example(type_ref: TypeRef) -> str | None:
            example = registry.example_for_type_ref(type_ref)
            if example is None:
                return None
            # markdown table cells can't contain real newlines, so a
            # pretty-printed example is rendered as raw HTML: indentation
            # becomes &nbsp; and line breaks become <br>, wrapped in <code>
            # so it still reads like formatted JSON inside the cell.
            pretty = json.dumps(example, ensure_ascii=False, indent=2)
            html_lines = []
            for line in pretty.split("\n"):
                stripped = line.lstrip(" ")
                indent = len(line) - len(stripped)
                html_lines.append("&nbsp;" * indent + stripped.replace("|", "\\|"))
            return "<code>" + "<br>".join(html_lines) + "</code>"

        self.env.globals["json_example"] = json_example

    def _render_api_docs(
        self,
        ctx: PipelineContext,
        service_name: str,
        output_dir: Path,
    ) -> list[DocOutput]:
        """Render API.md index + one file per directory + optional grpc.md."""
        repo_root = ctx.local_repo_path or Path("/")
        public = ctx.public_symbols
        symbol_groups = _group_symbols_by_dir(public, repo_root)
        docs: list[DocOutput] = []

        # build mapping dir_name → relative file path (for the index)
        dir_files: dict[str, str] = {
            dir_name: _dir_to_file_path(dir_name)
            for dir_name in symbol_groups
        }
        dir_counts: dict[str, int] = {
            dir_name: len(syms) for dir_name, syms in symbol_groups.items()
        }
        nav_categories = _categorize_dirs(list(symbol_groups.keys()))

        # API.md — index only
        index_content = self._render(
            "API.md.j2",
            service_name=service_name,
            nav_categories=nav_categories,
            dir_files=dir_files,
            dir_counts=dir_counts,
            proto_services=ctx.proto_services,
            make_anchor=_make_anchor,
        )
        docs.append(DocOutput(path=output_dir / "API.md", content=index_content, doc_type="api"))

        # one file per directory
        common = dict(
            service_name=service_name,
            repo_url=ctx.source_base_url,
            branch=ctx.repo_branch,
            repo_root=repo_root,
            make_anchor=_make_anchor,
        )
        for dir_name, syms in symbol_groups.items():
            rel_file = _dir_to_file_path(dir_name)
            dir_content = self._render(
                "API_DIR.md.j2",
                dir_name=dir_name,
                symbols=syms,
                back_link=_back_link(rel_file),
                **common,
            )
            docs.append(DocOutput(
                path=output_dir / rel_file,
                content=dir_content,
                doc_type="api",
            ))

        # grpc.md
        if ctx.proto_services:
            grpc_content = self._render(
                "API_GRPC.md.j2",
                service_name=service_name,
                proto_services=ctx.proto_services,
                back_link=_back_link("api/grpc.md"),
                make_anchor=_make_anchor,
            )
            docs.append(DocOutput(
                path=output_dir / "api" / "grpc.md",
                content=grpc_content,
                doc_type="api",
            ))

        return docs

    async def render_all(
        self,
        ctx: PipelineContext,
        release_notes: list[ReleaseNote] | None = None,
    ) -> list[DocOutput]:
        output_dir = ctx.output_dir
        service_name = _service_name(ctx)
        docs: list[DocOutput] = []
        public_symbols = ctx.public_symbols
        self._set_json_example_global(ctx)

        # README
        docs.append(DocOutput(
            path=output_dir / "README.md",
            content=self._render(
                "README.md.j2",
                service_name=service_name,
                version=ctx.git_tags[-1] if ctx.git_tags else "unknown",
                detected_language=ctx.detected_language or "unknown",
                public_symbol_count=len(public_symbols),
                proto_service_count=len(ctx.proto_services),
                test_file_count=len(ctx.coverage_result.test_files) if ctx.coverage_result else 0,
                coverage_pct=ctx.coverage_result.overall_pct if ctx.coverage_result else None,
                external_dep_count=len(ctx.external_deps),
                external_deps=ctx.external_deps,
                has_proto=bool(ctx.proto_services),
                has_tests=bool(ctx.coverage_result),
                has_er=bool(ctx.er_entities),
                has_release_notes=bool(release_notes),
                overview=None,
            ),
            doc_type="readme",
        ))

        # API — index + per-directory files
        docs.extend(self._render_api_docs(ctx, service_name, output_dir))

        # TESTS
        raw_test_files = ctx.coverage_result.test_files if ctx.coverage_result else []
        sorted_test_files = sorted(raw_test_files, key=lambda tf: str(tf.path).lower())
        docs.append(DocOutput(
            path=output_dir / "TESTS.md",
            content=self._render(
                "TESTS.md.j2",
                service_name=service_name,
                coverage=ctx.coverage_result,
                test_files=sorted_test_files,
            ),
            doc_type="tests",
        ))

        # ER
        if ctx.er_entities:
            docs.append(DocOutput(
                path=output_dir / "ER.md",
                content=self._render(
                    "ER.md.j2",
                    service_name=service_name,
                    er_diagram=ctx.er_diagram or "",
                    entities=ctx.er_entities,
                ),
                doc_type="er",
            ))

        # CHANGELOG
        if ctx.git_history:
            by_tag: dict[str, dict] = {}
            for tag in ctx.git_tags:
                tag_entries = [e for e in ctx.git_history if e.tag == tag]
                deduped = deduplicate(tag_entries)
                grouped = group_entries(deduped)
                if grouped:
                    by_tag[tag] = grouped
            docs.append(DocOutput(
                path=output_dir / "CHANGELOG.md",
                content=self._render(
                    "CHANGELOG.md.j2",
                    service_name=service_name,
                    changelog_by_tag=by_tag,
                ),
                doc_type="changelog",
            ))

        # RELEASE_NOTES — skip existing (incremental)
        if release_notes:
            rn_dir = output_dir / "RELEASE_NOTES"
            rn_dir.mkdir(parents=True, exist_ok=True)
            for note in release_notes:
                rn_path = rn_dir / f"{note.tag}.md"
                if rn_path.exists():
                    logger.info("RELEASE_NOTES/%s.md exists, skipping", note.tag)
                    continue
                docs.append(DocOutput(
                    path=rn_path,
                    content=self._render(
                        "RELEASE_NOTES.md.j2",
                        service_name=service_name,
                        note=note,
                    ),
                    doc_type="release_notes",
                ))

        # write to disk
        for doc in docs:
            doc.path.parent.mkdir(parents=True, exist_ok=True)
            doc.path.write_text(doc.content, encoding="utf-8")
            logger.info("Written: %s", doc.path)

        return docs
