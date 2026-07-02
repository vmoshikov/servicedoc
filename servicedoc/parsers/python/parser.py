from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import ClassVar

import tree_sitter_python as tsp
from tree_sitter import Language, Node, Parser, Query, QueryCursor

from servicedoc.models.symbols import ClassSymbol, FunctionSymbol, Parameter, Symbol, TypeRef
from servicedoc.parsers.base import LanguageParser

from .queries import QUERY_CLASSES, QUERY_FUNCTIONS

logger = logging.getLogger(__name__)

PY_LANGUAGE = Language(tsp.language())
_PARSER = Parser(PY_LANGUAGE)

_func_query = Query(PY_LANGUAGE, QUERY_FUNCTIONS)
_class_query = Query(PY_LANGUAGE, QUERY_CLASSES)


def _node_text(node: Node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _is_public(name: str) -> bool:
    return not name.startswith("_")


def _extract_docstring(body_node: Node, source: bytes) -> str | None:
    for child in body_node.children:
        if child.type == "expression_statement":
            for sub in child.children:
                if sub.type == "string":
                    raw = _node_text(sub, source)
                    return raw.strip('"""').strip("'''").strip('"').strip("'").strip()
        break
    return None


def _extract_comment_above(source_lines: list[bytes], line_start: int) -> str | None:
    comment_lines: list[str] = []
    for i in range(line_start - 2, -1, -1):
        stripped = source_lines[i].strip()
        if stripped.startswith(b"#"):
            comment_lines.append(stripped[1:].decode("utf-8", errors="replace").strip())
        elif stripped == b"":
            continue
        else:
            break
    if not comment_lines:
        return None
    return "\n".join(reversed(comment_lines))


def _parse_params(params_node: Node, source: bytes) -> list[Parameter]:
    params: list[Parameter] = []
    for child in params_node.children:
        if child.type in ("identifier", "typed_parameter", "typed_default_parameter"):
            name = ""
            type_name = "Any"
            if child.type == "identifier":
                name = _node_text(child, source)
            else:
                for sub in child.children:
                    if sub.type == "identifier" and not name:
                        name = _node_text(sub, source)
                    elif sub.type == "type":
                        type_name = _node_text(sub, source)
            if name and name not in ("self", "cls"):
                params.append(Parameter(name=name, type_ref=TypeRef(name=type_name)))
    return params


class PythonParser(LanguageParser):
    language_name: ClassVar[str] = "python"
    extensions: ClassVar[frozenset[str]] = frozenset({".py"})

    async def parse_file(self, path: Path) -> list[Symbol]:
        source = await asyncio.to_thread(path.read_bytes)
        return await asyncio.to_thread(self._extract_symbols, source, path)

    def _extract_symbols(self, source: bytes, path: Path) -> list[Symbol]:
        tree = _PARSER.parse(source)
        source_lines = source.split(b"\n")
        symbols: list[Symbol] = []

        # functions (top-level and methods)
        for match in QueryCursor(_func_query).matches(tree.root_node):
            for cap_name, cap_nodes in match[1].items():
                if cap_name != "func.name":
                    continue
                for name_node in cap_nodes:
                    name = _node_text(name_node, source)
                    if not _is_public(name):
                        continue
                    func_node = name_node.parent
                    if func_node is None:
                        continue

                    # extract docstring or comment
                    docstring: str | None = None
                    params_node: Node | None = None
                    return_type_node: Node | None = None
                    body_node: Node | None = None

                    for child in func_node.children:
                        if child.type == "parameters":
                            params_node = child
                        elif child.type == "type":
                            return_type_node = child
                        elif child.type == "block":
                            body_node = child
                            docstring = _extract_docstring(child, source)

                    comment = docstring or _extract_comment_above(
                        source_lines, func_node.start_point[0]
                    )
                    params = _parse_params(params_node, source) if params_node else []
                    return_types = (
                        [TypeRef(name=_node_text(return_type_node, source))]
                        if return_type_node else []
                    )

                    kind: str = "method" if self._is_method(func_node) else "function"
                    symbols.append(FunctionSymbol(
                        name=name,
                        kind=kind,  # type: ignore[arg-type]
                        file_path=path,
                        line_start=func_node.start_point[0] + 1,
                        line_end=func_node.end_point[0] + 1,
                        is_public=True,
                        parameters=params,
                        return_types=return_types,
                        comment=comment,
                        needs_ai=comment is None,
                    ))

        # classes
        for match in QueryCursor(_class_query).matches(tree.root_node):
            for cap_name, cap_nodes in match[1].items():
                if cap_name != "class.name":
                    continue
                for name_node in cap_nodes:
                    name = _node_text(name_node, source)
                    if not _is_public(name):
                        continue
                    class_node = name_node.parent
                    if class_node is None:
                        continue

                    docstring = None
                    base_classes: list[str] = []
                    for child in class_node.children:
                        if child.type == "argument_list":
                            for base in child.children:
                                if base.type in ("identifier", "dotted_name"):
                                    base_classes.append(_node_text(base, source))
                        elif child.type == "block":
                            docstring = _extract_docstring(child, source)

                    comment = docstring or _extract_comment_above(
                        source_lines, class_node.start_point[0]
                    )
                    symbols.append(ClassSymbol(
                        name=name,
                        kind="class",
                        file_path=path,
                        line_start=class_node.start_point[0] + 1,
                        line_end=class_node.end_point[0] + 1,
                        is_public=True,
                        base_classes=base_classes,
                        comment=comment,
                        needs_ai=comment is None,
                    ))

        return symbols

    def _is_method(self, func_node: Node) -> bool:
        parent = func_node.parent
        while parent:
            if parent.type == "class_definition":
                return True
            parent = parent.parent
        return False

    async def get_imports(self, path: Path) -> list[str]:
        source = await asyncio.to_thread(path.read_bytes)
        tree = _PARSER.parse(source)
        from .queries import QUERY_IMPORTS, QUERY_IMPORTS_FROM
        imports: list[str] = []
        for q_str in (QUERY_IMPORTS, QUERY_IMPORTS_FROM):
            q = Query(PY_LANGUAGE, q_str)
            for match in QueryCursor(q).matches(tree.root_node):
                for _, nodes in match[1].items():
                    for node in nodes:
                        imports.append(_node_text(node, source))
        return imports
