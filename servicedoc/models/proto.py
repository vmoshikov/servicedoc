from pathlib import Path
from typing import Literal

from pydantic import BaseModel


class ProtoField(BaseModel):
    name: str
    type: str
    number: int
    label: Literal["optional", "required", "repeated"] = "optional"


class ProtoMessage(BaseModel):
    name: str
    fields: list[ProtoField] = []

    def to_json_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {f.name: {"type": f.type, "field_number": f.number} for f in self.fields},
        }


class ProtoMethod(BaseModel):
    name: str
    input_type: str
    output_type: str
    client_streaming: bool = False
    server_streaming: bool = False


class ProtoService(BaseModel):
    name: str
    methods: list[ProtoMethod] = []
    file_path: Path
