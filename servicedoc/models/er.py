from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel


class ERFieldKind(str, Enum):
    PK = "PK"
    FK = "FK"
    FIELD = ""


class ERField(BaseModel):
    name: str
    type: str
    kind: ERFieldKind = ERFieldKind.FIELD
    nullable: bool = True


class EREntity(BaseModel):
    name: str
    table_name: str | None = None
    fields: list[ERField] = []
    source_file: Path
    orm_type: Literal["gorm", "sqlalchemy", "raw_sql", "unknown"] = "unknown"

    @property
    def effective_table_name(self) -> str:
        return self.table_name or self.name.lower() + "s"


class ERRelation(BaseModel):
    from_entity: str
    to_entity: str
    kind: Literal["one_to_one", "one_to_many", "many_to_many"]
    label: str = ""
    is_inferred: bool = False
