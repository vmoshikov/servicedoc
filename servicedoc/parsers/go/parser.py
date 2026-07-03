from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import ClassVar

import tree_sitter_go as tsg
from tree_sitter import Language, Node, Parser, Query, QueryCursor

from servicedoc.models.symbols import (
    ClassSymbol,
    ConstSymbol,
    FunctionSymbol,
    Parameter,
    SwitchCase,
    SwitchStringMap,
    Symbol,
    TypeRef,
)
from servicedoc.parsers.base import LanguageParser

from .queries import QUERY_FUNCTIONS, QUERY_METHODS, QUERY_STRUCTS, QUERY_INTERFACES

logger = logging.getLogger(__name__)

GO_LANGUAGE = Language(tsg.language())
_PARSER = Parser(GO_LANGUAGE)

_func_query = Query(GO_LANGUAGE, QUERY_FUNCTIONS)
_method_query = Query(GO_LANGUAGE, QUERY_METHODS)
_struct_query = Query(GO_LANGUAGE, QUERY_STRUCTS)
_iface_query = Query(GO_LANGUAGE, QUERY_INTERFACES)


def _node_text(node: Node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _is_exported(name: str) -> bool:
    return bool(name) and name[0].isupper()


def _extract_comment_above(source_lines: list[bytes], line_start: int) -> str | None:
    comment_lines: list[str] = []
    for i in range(line_start - 1, -1, -1):
        stripped = source_lines[i].strip()
        if stripped.startswith(b"//"):
            comment_lines.append(stripped[2:].decode("utf-8", errors="replace").strip())
        else:
            # blank line or non-comment → stop (Go doc comments have no gap)
            break
    if not comment_lines:
        return None
    return "\n".join(reversed(comment_lines))


def _parse_type_ref(node: Node, source: bytes) -> TypeRef:
    text = _node_text(node, source).strip()
    is_pointer = text.startswith("*")
    if is_pointer:
        text = text[1:]
    parts = text.split(".")
    if len(parts) == 2:
        return TypeRef(name=parts[1], package=parts[0], is_pointer=is_pointer)
    return TypeRef(name=text, is_pointer=is_pointer)


def _parse_params(param_list_node: Node, source: bytes) -> list[Parameter]:
    params: list[Parameter] = []
    for child in param_list_node.children:
        if child.type == "parameter_declaration":
            name_nodes = [c for c in child.children if c.type == "identifier"]
            type_nodes = [c for c in child.children if c.type not in ("identifier", ",", "(", ")")]
            if not type_nodes:
                continue
            type_ref = _parse_type_ref(type_nodes[-1], source)
            for name_node in name_nodes:
                params.append(Parameter(name=_node_text(name_node, source), type_ref=type_ref))
            if not name_nodes:
                params.append(Parameter(name="_", type_ref=type_ref))
    return params


_RETURN_TYPE_NODE_TYPES = frozenset({
    "type_identifier", "pointer_type", "qualified_type", "slice_type",
    "map_type", "generic_type", "array_type", "interface_type",
    "struct_type", "function_type", "channel_type",
})


def _parse_return_types(node: Node, source: bytes) -> list[TypeRef]:
    """Parse a function/method return clause: either a single type node,
    or a parenthesized `parameter_list` of (possibly named) types."""
    if node.type != "parameter_list":
        return [_parse_type_ref(node, source)]
    return_types: list[TypeRef] = []
    for child in node.children:
        if child.type == "parameter_declaration":
            type_nodes = [c for c in child.children if c.type not in ("identifier", ",", "(", ")")]
            if type_nodes:
                return_types.append(_parse_type_ref(type_nodes[-1], source))
        elif child.type in _RETURN_TYPE_NODE_TYPES:
            return_types.append(_parse_type_ref(child, source))
    return return_types


_JSON_TAG_RE = re.compile(r'json:"([^"]*)"')


def _extract_json_name(decl: Node, source: bytes) -> str | None:
    """Extract the `json:"..."` tag value (could be "", "-", or a real name)."""
    tag_node = next((c for c in decl.children if c.type == "raw_string_literal"), None)
    if tag_node is None:
        return None
    tag_text = _node_text(tag_node, source).strip("`")
    m = _JSON_TAG_RE.search(tag_text)
    if not m:
        return None
    return m.group(1).split(",")[0]


def _parse_struct_fields(struct_type_node: Node, source: bytes, source_lines: list[bytes]) -> list[Parameter]:
    fields: list[Parameter] = []
    body = next((c for c in struct_type_node.children if c.type == "field_declaration_list"), None)
    if body is None:
        return fields
    for decl in body.children:
        if decl.type != "field_declaration":
            continue
        name_nodes = [c for c in decl.children if c.type == "field_identifier"]
        type_nodes = [
            c for c in decl.children
            if c.type not in ("field_identifier", ",", "raw_string_literal")
        ]
        if not type_nodes:
            continue
        type_ref = _parse_type_ref(type_nodes[-1], source)
        json_name = _extract_json_name(decl, source)
        comment = _extract_comment_above(source_lines, decl.start_point[0])
        if name_nodes:
            for name_node in name_nodes:
                fields.append(Parameter(
                    name=_node_text(name_node, source), type_ref=type_ref,
                    json_name=json_name, comment=comment,
                ))
        else:
            # embedded/anonymous field: name equals the type name
            fields.append(Parameter(
                name=type_ref.name, type_ref=type_ref, json_name=json_name, comment=comment,
            ))
    return fields


def _find_first(node: Node, type_name: str) -> Node | None:
    if node.type == type_name:
        return node
    for child in node.children:
        found = _find_first(child, type_name)
        if found is not None:
            return found
    return None


def _string_literal_value(node: Node, source: bytes) -> str | None:
    if node.type != "interpreted_string_literal":
        return None
    content = next((c for c in node.children if c.type == "interpreted_string_literal_content"), None)
    return _node_text(content, source) if content is not None else ""


def _single_return_string(stmt_list: Node, source: bytes) -> str | None:
    """None unless stmt_list is exactly one `return "literal"` — anything
    more complex (multiple statements, non-literal return, multi-value
    return) disqualifies the whole switch from being a message map."""
    stmts = [c for c in stmt_list.children if c.type == "return_statement"]
    other_stmts = [c for c in stmt_list.children if c.type not in ("return_statement", ",")]
    if len(stmts) != 1 or other_stmts:
        return None
    expr_list = next((c for c in stmts[0].children if c.type == "expression_list"), None)
    if expr_list is None:
        return None
    literals = [c for c in expr_list.children if c.type == "interpreted_string_literal"]
    if len(literals) != 1:
        return None
    return _string_literal_value(literals[0], source)


def _extract_switch_string_map(block_node: Node, source: bytes) -> SwitchStringMap | None:
    """Detects `switch param { case "a": return "msg" ... default: return "d" }`
    — a fixed string-to-string lookup, e.g. an operation-type-to-title map.
    Bails (returns None) if any branch isn't a single string-literal return,
    since that means it's not a pure lookup table."""
    switch_node = _find_first(block_node, "expression_switch_statement")
    if switch_node is None:
        return None
    subject_node = next((c for c in switch_node.children if c.type == "identifier"), None)
    if subject_node is None:
        return None

    cases: list[SwitchCase] = []
    default_message: str | None = None
    has_default = False

    for child in switch_node.children:
        if child.type == "expression_case":
            expr_list = next((c for c in child.children if c.type == "expression_list"), None)
            stmt_list = next((c for c in child.children if c.type == "statement_list"), None)
            if expr_list is None or stmt_list is None:
                return None
            message = _single_return_string(stmt_list, source)
            if message is None:
                return None
            case_values = [
                _string_literal_value(n, source)
                for n in expr_list.children if n.type == "interpreted_string_literal"
            ]
            if not case_values:
                return None
            for value in case_values:
                cases.append(SwitchCase(value=value or "", message=message))
        elif child.type == "default_case":
            has_default = True
            stmt_list = next((c for c in child.children if c.type == "statement_list"), None)
            if stmt_list is not None:
                default_message = _single_return_string(stmt_list, source)
                if default_message is None:
                    return None

    if not cases:
        return None
    if has_default and default_message is None:
        return None
    return SwitchStringMap(
        param_name=_node_text(subject_node, source),
        cases=cases,
        default_message=default_message,
    )


def _clean_comment_text(text: str) -> str:
    text = text.strip()
    if text.startswith("//"):
        return text[2:].strip()
    if text.startswith("/*") and text.endswith("*/"):
        return text[2:-2].strip()
    return text


_CONST_TYPE_NODE_TYPES = frozenset({"type_identifier", "qualified_type", "pointer_type"})


def _parse_consts(root_node: Node, source: bytes, source_lines: list[bytes], path: Path) -> list[ConstSymbol]:
    """Top-level `const` declarations only (single or grouped). Specs with
    no explicit `= value` (bare identifiers reusing the previous spec's
    expression, e.g. iota chains) are skipped rather than guessed at."""
    consts: list[ConstSymbol] = []
    for decl in root_node.children:
        if decl.type != "const_declaration":
            continue
        is_grouped = any(c.type == "(" for c in decl.children)
        # a single (non-grouped) const's doc comment sits outside the
        # declaration as a source-level sibling; a grouped one's per-spec
        # comments are children of the declaration itself, handled below.
        outer_comment = None if is_grouped else _extract_comment_above(source_lines, decl.start_point[0])
        pending_comment: str | None = None

        for child in decl.children:
            if child.type == "comment":
                pending_comment = _clean_comment_text(_node_text(child, source))
                continue
            if child.type != "const_spec":
                continue
            name_node = next((c for c in child.children if c.type == "identifier"), None)
            expr_list = next((c for c in child.children if c.type == "expression_list"), None)
            if name_node is None or expr_list is None:
                pending_comment = None
                continue
            type_node = next((c for c in child.children if c.type in _CONST_TYPE_NODE_TYPES), None)
            name = _node_text(name_node, source)
            comment = pending_comment or outer_comment
            consts.append(ConstSymbol(
                name=name,
                kind="const",
                file_path=path,
                line_start=child.start_point[0] + 1,
                line_end=child.end_point[0] + 1,
                is_public=_is_exported(name),
                value=_node_text(expr_list, source),
                type_name=_node_text(type_node, source) if type_node else None,
                comment=comment,
                needs_ai=comment is None,
            ))
            pending_comment = None
    return consts


class GoParser(LanguageParser):
    language_name: ClassVar[str] = "go"
    extensions: ClassVar[frozenset[str]] = frozenset({".go"})

    async def parse_file(self, path: Path) -> list[Symbol]:
        source = await asyncio.to_thread(path.read_bytes)
        return await asyncio.to_thread(self._extract_symbols, source, path)

    def _extract_symbols(self, source: bytes, path: Path) -> list[Symbol]:
        tree = _PARSER.parse(source)
        source_lines = source.split(b"\n")
        symbols: list[Symbol] = []

        # functions
        for match in QueryCursor(_func_query).matches(tree.root_node):
            for cap_name, cap_nodes in match[1].items():
                if cap_name != "func.name":
                    continue
                for name_node in cap_nodes:
                    name = _node_text(name_node, source)
                    exported = _is_exported(name)
                    func_node = name_node.parent
                    if func_node is None:
                        continue
                    params: list[Parameter] = []
                    return_types: list[TypeRef] = []
                    seen_params = False
                    for child in func_node.children:
                        if child.type == "parameter_list":
                            if not seen_params:
                                params = _parse_params(child, source)
                                seen_params = True
                            else:
                                return_types = _parse_return_types(child, source)
                        elif child.type in _RETURN_TYPE_NODE_TYPES:
                            return_types = _parse_return_types(child, source)

                    # unexported functions are skipped entirely, UNLESS they
                    # match the "string switch → string message" lookup
                    # pattern (e.g. an operation-type-to-title map) — those
                    # are worth surfacing in a message-map registry even
                    # though they're private implementation details.
                    message_map = None
                    if len(return_types) == 1 and return_types[0].name == "string":
                        body_node = next((c for c in func_node.children if c.type == "block"), None)
                        if body_node is not None:
                            message_map = _extract_switch_string_map(body_node, source)
                    if not exported and message_map is None:
                        continue

                    comment = _extract_comment_above(source_lines, func_node.start_point[0])
                    symbols.append(FunctionSymbol(
                        name=name,
                        kind="function",
                        file_path=path,
                        line_start=func_node.start_point[0] + 1,
                        line_end=func_node.end_point[0] + 1,
                        is_public=exported,
                        parameters=params,
                        return_types=return_types,
                        message_map=message_map,
                        comment=comment,
                        needs_ai=comment is None,
                    ))

        # methods
        for match in QueryCursor(_method_query).matches(tree.root_node):
            for cap_name, cap_nodes in match[1].items():
                if cap_name != "method.name":
                    continue
                for name_node in cap_nodes:
                    name = _node_text(name_node, source)
                    exported = _is_exported(name)
                    method_node = name_node.parent
                    if method_node is None:
                        continue
                    receiver = ""
                    params: list[Parameter] = []
                    return_types: list[TypeRef] = []
                    param_list_index = 0
                    for child in method_node.children:
                        if child.type == "parameter_list":
                            if param_list_index == 0:
                                receiver = _node_text(child, source)
                            elif param_list_index == 1:
                                params = _parse_params(child, source)
                            else:
                                return_types = _parse_return_types(child, source)
                            param_list_index += 1
                        elif param_list_index >= 2 and child.type in _RETURN_TYPE_NODE_TYPES:
                            return_types = _parse_return_types(child, source)

                    # see the "functions" loop above for why unexported
                    # methods aren't skipped unconditionally
                    message_map = None
                    if len(return_types) == 1 and return_types[0].name == "string":
                        body_node = next((c for c in method_node.children if c.type == "block"), None)
                        if body_node is not None:
                            message_map = _extract_switch_string_map(body_node, source)
                    if not exported and message_map is None:
                        continue

                    comment = _extract_comment_above(source_lines, method_node.start_point[0])
                    symbols.append(FunctionSymbol(
                        name=name,
                        kind="method",
                        file_path=path,
                        line_start=method_node.start_point[0] + 1,
                        line_end=method_node.end_point[0] + 1,
                        is_public=exported,
                        receiver=receiver,
                        parameters=params,
                        return_types=return_types,
                        message_map=message_map,
                        comment=comment,
                        needs_ai=comment is None,
                    ))

        # structs
        for match in QueryCursor(_struct_query).matches(tree.root_node):
            caps = match[1]
            for name_node in caps.get("struct.name", []):
                name = _node_text(name_node, source)
                if not _is_exported(name):
                    continue
                type_spec_node = name_node.parent
                if type_spec_node is None:
                    continue
                struct_body = next(
                    (c for c in type_spec_node.children if c.type == "struct_type"), None
                )
                if struct_body is None:
                    continue
                type_params_node = next(
                    (c for c in type_spec_node.children if c.type == "type_parameter_list"), None
                )
                type_params = _node_text(type_params_node, source) if type_params_node else None
                # use the type_spec's own range, not its parent type_declaration:
                # Go allows grouping several types in one `type ( ... )` block,
                # where multiple type_specs share the same parent — using the
                # parent would give every struct in the group identical
                # line_start/line_end (and thus identical code sent to the AI).
                comment = _extract_comment_above(source_lines, type_spec_node.start_point[0])
                symbols.append(ClassSymbol(
                    name=name,
                    kind="struct",
                    file_path=path,
                    line_start=type_spec_node.start_point[0] + 1,
                    line_end=type_spec_node.end_point[0] + 1,
                    is_public=True,
                    fields=_parse_struct_fields(struct_body, source, source_lines),
                    type_params=type_params,
                    comment=comment,
                    needs_ai=comment is None,
                ))

        symbols.extend(_parse_consts(tree.root_node, source, source_lines, path))

        return symbols

    async def get_imports(self, path: Path) -> list[str]:
        from .queries import QUERY_IMPORTS
        source = await asyncio.to_thread(path.read_bytes)
        tree = _PARSER.parse(source)
        q = Query(GO_LANGUAGE, QUERY_IMPORTS)
        imports = []
        for match in QueryCursor(q).matches(tree.root_node):
            for cap_name, cap_nodes in match[1].items():
                if cap_name == "import.path":
                    for node in cap_nodes:
                        text = _node_text(node, source).strip('"')
                        imports.append(text)
        return imports
