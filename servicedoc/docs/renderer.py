from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from servicedoc.docs.changelog import deduplicate, group_entries
from servicedoc.docs.json_example import TypeRegistry
from servicedoc.models.docs import DocOutput, ReleaseNote
from servicedoc.models.pipeline import PipelineContext
from servicedoc.models.proto import ProtoMessage, ProtoService
from servicedoc.models.symbols import Symbol, TypeRef
from servicedoc.utils.source_links import make_source_ref

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).parent / "templates"


def _service_name(ctx: PipelineContext) -> str:
    if ctx.repo_config.name:
        return ctx.repo_config.name
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
    return re.sub(r"[^\w\- ]", "", text.lower()).replace(" ", "-")


def _dir_to_file_path(dir_name: str, prefix: str) -> str:
    """Convert dir key to relative file path under `prefix/`. '.' → prefix/root.md"""
    if dir_name == ".":
        return f"{prefix}/root.md"
    return f"{prefix}/{dir_name}.md"


def _back_link(file_path: str, index_name: str) -> str:
    """Relative link back to the family index (API.md / FUNCTIONS.md / ...) from a nested file."""
    depth = file_path.count("/")
    return "../" * depth + index_name


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


_FUNCS_KINDS = ("function", "method")
_STRUCTS_KINDS = ("class", "struct", "interface")

_PROTO_MAP_TYPE_RE = re.compile(r"^map<\s*\w+\s*,\s*(\w+)\s*>$")


def _relevant_proto_objects(ctx: PipelineContext, service_name: str) -> tuple[list[ProtoService], list[ProtoMessage]]:
    """A shared/vendored proto repo can hold contracts for many unrelated
    services. Keep only proto files whose path contains the service's own
    name (e.g. `--name dahubapi` matches `.../dahubapi/v1/extension_service.proto`
    but not `.../api_gateway/api_gateway_service.proto`) — everything else is
    someone else's service and gets ignored. Nested message types reachable
    from a matched message (e.g. a shared `Pagination`) are still pulled in,
    even if their own .proto file doesn't contain the name, since they're
    part of the actual wire contract."""
    proto_by_name = {m.name: m for m in ctx.proto_messages}
    needle = service_name.lower()

    def _matches(file_path: Path | None) -> bool:
        return file_path is not None and needle in str(file_path).lower()

    relevant_services = [svc for svc in ctx.proto_services if _matches(svc.file_path)]

    seed_names = {m.name for m in ctx.proto_messages if _matches(m.file_path)}
    for svc in relevant_services:
        for m in svc.methods:
            seed_names.add(m.input_type)
            seed_names.add(m.output_type)

    relevant_names: set[str] = set()
    queue = list(seed_names)
    while queue:
        name = queue.pop()
        if name in relevant_names:
            continue
        msg = proto_by_name.get(name)
        if msg is None:
            continue
        relevant_names.add(name)
        for field in msg.fields:
            candidate = field.type
            if m := _PROTO_MAP_TYPE_RE.match(field.type):
                candidate = m.group(1)
            if candidate in proto_by_name and candidate not in relevant_names:
                queue.append(candidate)

    relevant_messages = [m for m in ctx.proto_messages if m.name in relevant_names]
    return relevant_services, relevant_messages


_PROTO_VISIBILITY_ORDER = ["public", "private"]
_PROTO_VISIBILITY_OTHER = "other"


def _proto_visibility(file_path: Path | None) -> str:
    """`proto/public/...` vs `proto/private/...` — same service name can
    exist in both trees (public-facing contract vs internal one), so group
    separately instead of colliding them under one flat list."""
    if file_path is None:
        return _PROTO_VISIBILITY_OTHER
    parts = set(Path(file_path).parts)
    for v in _PROTO_VISIBILITY_ORDER:
        if v in parts:
            return v
    return _PROTO_VISIBILITY_OTHER


def _group_proto_by_visibility(
    services: list[ProtoService], messages: list[ProtoMessage],
) -> dict[str, dict[str, list]]:
    groups: dict[str, dict[str, list]] = {
        v: {"services": [], "messages": []}
        for v in [*_PROTO_VISIBILITY_ORDER, _PROTO_VISIBILITY_OTHER]
    }
    for svc in services:
        groups[_proto_visibility(svc.file_path)]["services"].append(svc)
    for msg in messages:
        groups[_proto_visibility(msg.file_path)]["messages"].append(msg)
    return {k: v for k, v in groups.items() if v["services"] or v["messages"]}


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

        def json_example_for_name(name: str) -> str | None:
            # plain multi-line JSON for a fenced ```json code block (not a
            # table cell), looked up directly by type/struct name.
            example = registry.example_for_type_ref(TypeRef(name=name))
            if example is None:
                return None
            return json.dumps(example, ensure_ascii=False, indent=2)

        self.env.globals["json_example"] = json_example
        self.env.globals["json_example_for_name"] = json_example_for_name

    def _set_proto_source_ref_global(self, ctx: PipelineContext) -> None:
        local_root = ctx.local_repo_path or Path("/")
        proto_root = ctx.proto_repo_path

        def proto_source_ref(file_path: Path, line_start: int, line_end: int | None = None) -> str:
            if proto_root is not None:
                try:
                    file_path.relative_to(proto_root)
                    return make_source_ref(
                        ctx.proto_repo_base_url, ctx.proto_repo_branch, file_path, proto_root, line_start, line_end,
                    )
                except ValueError:
                    pass
            return make_source_ref(ctx.source_base_url, ctx.repo_branch, file_path, local_root, line_start, line_end)

        self.env.globals["proto_source_ref"] = proto_source_ref

    def _render_symbol_family_docs(
        self,
        ctx: PipelineContext,
        service_name: str,
        output_dir: Path,
        symbols: list[Symbol],
        dir_prefix: str,
        index_filename: str,
        title: str,
        doc_type: str,
        title_emoji: str = "",
    ) -> list[DocOutput]:
        """Generic: index + one file per directory for a symbol subset
        (funcs-only for FUNCTIONS.md, structs-only for STRUCTURES.md)."""
        repo_root = ctx.local_repo_path or Path("/")
        symbol_groups = _group_symbols_by_dir(symbols, repo_root)
        docs: list[DocOutput] = []

        dir_files = {d: _dir_to_file_path(d, dir_prefix) for d in symbol_groups}
        dir_counts = {d: len(s) for d, s in symbol_groups.items()}
        nav_categories = _categorize_dirs(list(symbol_groups.keys()))

        index_content = self._render(
            "SYMBOL_INDEX.md.j2",
            service_name=service_name,
            title=title,
            title_emoji=title_emoji,
            doc_type=doc_type,
            nav_categories=nav_categories,
            dir_files=dir_files,
            dir_counts=dir_counts,
        )
        docs.append(DocOutput(path=output_dir / index_filename, content=index_content, doc_type=doc_type))

        common = dict(
            service_name=service_name,
            repo_url=ctx.source_base_url,
            branch=ctx.repo_branch,
            repo_root=repo_root,
            make_anchor=_make_anchor,
        )
        for dir_name, syms in symbol_groups.items():
            rel_file = dir_files[dir_name]
            dir_content = self._render(
                "API_DIR.md.j2",
                dir_name=dir_name,
                symbols=syms,
                back_link=_back_link(rel_file, index_filename),
                **common,
            )
            docs.append(DocOutput(path=output_dir / rel_file, content=dir_content, doc_type=doc_type))

        return docs

    def _render_proto_api_md(self, ctx: PipelineContext, service_name: str, output_dir: Path) -> DocOutput:
        relevant_services, relevant_messages = _relevant_proto_objects(ctx, service_name)
        proto_groups = _group_proto_by_visibility(relevant_services, relevant_messages)
        self._set_proto_source_ref_global(ctx)
        content = self._render(
            "API.md.j2",
            service_name=service_name,
            proto_groups=proto_groups,
            make_anchor=_make_anchor,
        )
        return DocOutput(path=output_dir / "API.md", content=content, doc_type="api")

    async def render_all(
        self,
        ctx: PipelineContext,
        release_notes: list[ReleaseNote] | None = None,
        overview: str | None = None,
        contributors: list[tuple[str, str, int]] | None = None,
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
                test_file_count=len(ctx.detected_test_files),
                coverage_pct=ctx.coverage_result.overall_pct if ctx.coverage_result else None,
                external_dep_count=len(ctx.external_deps),
                external_deps=ctx.external_deps,
                has_proto=bool(ctx.proto_services),
                has_tests=bool(ctx.coverage_result),
                has_er=bool(ctx.er_diagram),
                has_release_notes=bool(release_notes),
                overview=overview,
                contributors=contributors or [],
                provider_names=ctx.provider_names,
                test_match_report=ctx.test_match_report,
            ),
            doc_type="readme",
        ))

        # API.md — proto-only (gRPC services + messages actually used by this service)
        docs.append(self._render_proto_api_md(ctx, service_name, output_dir))

        # FUNCTIONS.md — all public functions/methods, dir-based
        docs.extend(self._render_symbol_family_docs(
            ctx, service_name, output_dir,
            symbols=[s for s in public_symbols if s.kind in _FUNCS_KINDS],
            dir_prefix="functions",
            index_filename="FUNCTIONS.md",
            title="Функции и методы",
            doc_type="functions",
            title_emoji="⚙️",
        ))

        # STRUCTURES.md — all public structs/classes/interfaces, dir-based
        docs.extend(self._render_symbol_family_docs(
            ctx, service_name, output_dir,
            symbols=[s for s in public_symbols if s.kind in _STRUCTS_KINDS],
            dir_prefix="structures",
            index_filename="STRUCTURES.md",
            title="Структуры",
            doc_type="structures",
            title_emoji="🧱",
        ))

        # TESTS
        sorted_test_files = sorted(ctx.detected_test_files, key=lambda tf: str(tf.path).lower())
        docs.append(DocOutput(
            path=output_dir / "TESTS.md",
            content=self._render(
                "TESTS.md.j2",
                service_name=service_name,
                coverage=ctx.coverage_result,
                test_files=sorted_test_files,
                test_match_report=ctx.test_match_report,
            ),
            doc_type="tests",
        ))

        # ER
        if ctx.er_diagram:
            docs.append(DocOutput(
                path=output_dir / "ER.md",
                content=self._render(
                    "ER.md.j2",
                    service_name=service_name,
                    er_diagram=ctx.er_diagram or "",
                    entities=ctx.er_entities,
                    sql_functions=ctx.sql_functions,
                ),
                doc_type="er",
            ))

        # CHANGELOG
        if ctx.git_history:
            by_tag: dict[str, dict] = {}
            for tag in reversed(ctx.git_tags):
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
