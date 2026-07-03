from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict


class TypeRef(BaseModel):
    name: str
    package: str | None = None
    is_pointer: bool = False
    is_optional: bool = False
    generic_args: list[TypeRef] = []


class Parameter(BaseModel):
    name: str
    type_ref: TypeRef
    json_name: str | None = None  # from a `json:"..."` struct tag, if present
    comment: str | None = None  # leading `//` comment above a struct field


class Symbol(BaseModel):
    model_config = ConfigDict(frozen=False)

    name: str
    kind: Literal["function", "method", "class", "interface", "struct", "type_alias", "const"]
    file_path: Path
    line_start: int
    line_end: int
    is_public: bool
    comment: str | None = None
    ai_description: str | None = None
    needs_ai: bool = False

    @property
    def description(self) -> str | None:
        return self.comment or self.ai_description


class SwitchCase(BaseModel):
    value: str
    message: str


class SwitchStringMap(BaseModel):
    """A `switch param { case "x": return "msg" ... }` body that maps a
    string input to a fixed set of human-readable output strings — e.g. an
    operation-type-to-title lookup. Only recorded when every case (and the
    default, if present) is a single `return <string literal>`."""
    param_name: str
    cases: list[SwitchCase] = []
    default_message: str | None = None


class FunctionSymbol(Symbol):
    kind: Literal["function", "method", "class", "interface", "struct", "type_alias", "const"] = "function"
    parameters: list[Parameter] = []
    return_types: list[TypeRef] = []
    receiver: str | None = None
    message_map: SwitchStringMap | None = None


class ClassSymbol(Symbol):
    kind: Literal["function", "method", "class", "interface", "struct", "type_alias", "const"] = "class"
    methods: list[FunctionSymbol] = []
    fields: list[Parameter] = []
    base_classes: list[str] = []
    decorators: list[str] = []
    type_params: str | None = None  # raw generic parameter list, e.g. "[T comparable]"


class ConstSymbol(Symbol):
    kind: Literal["function", "method", "class", "interface", "struct", "type_alias", "const"] = "const"
    value: str = ""  # raw source text of the constant's expression
    type_name: str | None = None  # explicit type, if declared (e.g. "OpType" in `OpCreate OpType = "..."`)
