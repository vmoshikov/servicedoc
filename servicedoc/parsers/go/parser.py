from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import ClassVar

import tree_sitter_go as tsg
from tree_sitter import Language, Node, Parser, Query, QueryCursor

from servicedoc.models.symbols import FunctionSymbol, Parameter, Symbol, TypeRef
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
                    for child in func_node.children:
                        if child.type == "parameter_list":
                            params = _parse_params(child, source)
                        elif child.type in ("type_identifier", "pointer_type", "qualified_type",
                                            "slice_type", "map_type", "parameter_list"):
                            pass
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
                    for child in method_node.children:
                        if child.type == "parameter_list":
                            receiver = _node_text(child, source)
                            break
                    symbols.append(FunctionSymbol(
                        name=name,
                        kind="method",
                        file_path=path,
                        line_start=method_node.start_point[0] + 1,
                        line_end=method_node.end_point[0] + 1,
                        is_public=True,
                        receiver=receiver,
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
