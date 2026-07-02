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


class Symbol(BaseModel):
    model_config = ConfigDict(frozen=False)

    name: str
    kind: Literal["function", "method", "class", "interface", "struct", "type_alias"]
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


class FunctionSymbol(Symbol):
    kind: Literal["function", "method", "class", "interface", "struct", "type_alias"] = "function"
    parameters: list[Parameter] = []
    return_types: list[TypeRef] = []
    receiver: str | None = None


class ClassSymbol(Symbol):
    kind: Literal["function", "method", "class", "interface", "struct", "type_alias"] = "class"
    methods: list[FunctionSymbol] = []
    fields: list[Parameter] = []
    base_classes: list[str] = []
    decorators: list[str] = []
    type_params: str | None = None  # raw generic parameter list, e.g. "[T comparable]"
