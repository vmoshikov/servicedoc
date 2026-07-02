from __future__ import annotations

import re

from servicedoc.models.pipeline import PipelineContext
from servicedoc.models.proto import ProtoMessage
from servicedoc.models.symbols import ClassSymbol, TypeRef

_GO_SLICE_RE = re.compile(r"^\[\]\*?(.+)$")
_GO_MAP_RE = re.compile(r"^map\[(.+?)\]\*?(.+)$")
_PROTO_MAP_RE = re.compile(r"^map<\s*(\w+)\s*,\s*(\w+)\s*>$")

_SCALAR_DEFAULTS: dict[str, object] = {
    "string": "string", "bool": False, "bytes": "",
    "float": 0, "double": 0, "float32": 0, "float64": 0,
    "int": 0, "int8": 0, "int16": 0, "int32": 0, "int64": 0,
    "uint": 0, "uint8": 0, "uint16": 0, "uint32": 0, "uint64": 0,
    "sint32": 0, "sint64": 0, "fixed32": 0, "fixed64": 0,
    "sfixed32": 0, "sfixed64": 0, "byte": 0, "rune": 0,
}

_MAX_DEPTH = 4


class TypeRegistry:
    """Looks up message/struct field shapes by type name to build JSON examples."""

    def __init__(self, ctx: PipelineContext) -> None:
        self.proto_by_name: dict[str, ProtoMessage] = {m.name: m for m in ctx.proto_messages}
        self.struct_by_name: dict[str, ClassSymbol] = {
            s.name: s for s in ctx.symbols if isinstance(s, ClassSymbol) and s.kind == "struct"
        }

    def example_for_type_ref(self, type_ref: TypeRef) -> object | None:
        return _resolve(type_ref.name, self, seen=frozenset())


def _resolve(type_name: str, registry: TypeRegistry, seen: frozenset[str], depth: int = 0) -> object | None:
    type_name = type_name.strip().lstrip("*")

    if depth > _MAX_DEPTH:
        return None

    if m := _GO_SLICE_RE.match(type_name):
        inner = _resolve(m.group(1), registry, seen, depth + 1)
        return [inner] if inner is not None else []

    if m := _GO_MAP_RE.match(type_name):
        key_example = _resolve(m.group(1), registry, seen, depth + 1)
        val_example = _resolve(m.group(2), registry, seen, depth + 1)
        return {str(key_example) if key_example is not None else "key": val_example}

    if m := _PROTO_MAP_RE.match(type_name):
        val_example = _resolve(m.group(2), registry, seen, depth + 1)
        return {"key": val_example}

    if type_name in _SCALAR_DEFAULTS:
        return _SCALAR_DEFAULTS[type_name]

    if type_name in seen:
        return None  # cycle guard

    if msg := registry.proto_by_name.get(type_name):
        obj: dict[str, object] = {}
        for field in msg.fields:
            val = _resolve(field.type, registry, seen | {type_name}, depth + 1)
            obj[field.name] = [val] if field.label == "repeated" else val
        return obj

    if struct := registry.struct_by_name.get(type_name):
        obj = {}
        for param in struct.fields:
            obj[param.name] = _resolve(param.type_ref.name, registry, seen | {type_name}, depth + 1)
        return obj

    return None
