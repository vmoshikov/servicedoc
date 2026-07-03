from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import ClassVar

import tree_sitter_go as tsg
from tree_sitter import Language, Node, Parser, Query, QueryCursor

from servicedoc.models.symbols import ClassSymbol, FunctionSymbol, Parameter, Symbol, TypeRef
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


def _parse_struct_fields(struct_type_node: Node, source: bytes) -> list[Parameter]:
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
        if name_nodes:
            for name_node in name_nodes:
                fields.append(Parameter(
                    name=_node_text(name_node, source), type_ref=type_ref, json_name=json_name,
                ))
        else:
            # embedded/anonymous field: name equals the type name
            fields.append(Parameter(name=type_ref.name, type_ref=type_ref, json_name=json_name))
    return fields


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
                    if not _is_exported(name):
                        continue
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
                    comment = _extract_comment_above(source_lines, func_node.start_point[0])
                    symbols.append(FunctionSymbol(
                        name=name,
                        kind="function",
                        file_path=path,
                        line_start=func_node.start_point[0] + 1,
                        line_end=func_node.end_point[0] + 1,
                        is_public=True,
                        parameters=params,
                        return_types=return_types,
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
                    if not _is_exported(name):
                        continue
                    method_node = name_node.parent
                    if method_node is None:
                        continue
                    comment = _extract_comment_above(source_lines, method_node.start_point[0])
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
                    symbols.append(FunctionSymbol(
                        name=name,
                        kind="method",
                        file_path=path,
                        line_start=method_node.start_point[0] + 1,
                        line_end=method_node.end_point[0] + 1,
                        is_public=True,
                        receiver=receiver,
                        parameters=params,
                        return_types=return_types,
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
                    fields=_parse_struct_fields(struct_body, source),
                    type_params=type_params,
                    comment=comment,
                    needs_ai=comment is None,
                ))

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
