import re
from pathlib import Path

from servicedoc.models.proto import ProtoField, ProtoMessage, ProtoMethod, ProtoService

_MSG_OPEN = re.compile(r"^\s*message\s+(\w+)\s*\{")
_SVC_OPEN = re.compile(r"^\s*service\s+(\w+)\s*\{")
_RPC = re.compile(
    r"^\s*rpc\s+(\w+)\s*\((stream\s+)?(\w+)\)\s*returns\s*\((stream\s+)?(\w+)\)"
)
_FIELD = re.compile(
    r"^\s*(repeated\s+|optional\s+|required\s+)?(\w[\w.]+)\s+(\w+)\s*=\s*(\d+)\s*(?:\[.*\]\s*)?;"
)
_MAP_FIELD = re.compile(
    r"^\s*map\s*<\s*(\w+)\s*,\s*(\w+)\s*>\s+(\w+)\s*=\s*(\d+)\s*(?:\[.*\]\s*)?;"
)
_CLOSE = re.compile(r"^\s*\}")
_COMMENT = re.compile(r"^\s*//")


class ProtoFileParser:
    def parse(self, path: Path) -> tuple[list[ProtoService], list[ProtoMessage]]:
        lines = path.read_text(encoding="utf-8").splitlines()
        services: list[ProtoService] = []
        messages: list[ProtoMessage] = []
        stack: list[dict] = []
        depth = 0
        # comment lines immediately above a message/service/rpc definition
        # become its doc comment; any other line (field, blank, close-brace)
        # breaks the association.
        pending_comment: list[str] = []

        for lineno, line in enumerate(lines, start=1):
            if _COMMENT.match(line):
                pending_comment.append(line.strip()[2:].strip())
                continue
            depth += line.count("{") - line.count("}")

            if m := _MSG_OPEN.match(line):
                comment = "\n".join(pending_comment) if pending_comment else None
                pending_comment = []
                stack.append({
                    "kind": "message", "name": m.group(1), "depth": depth, "fields": [],
                    "line_start": lineno, "comment": comment,
                })
            elif m := _SVC_OPEN.match(line):
                comment = "\n".join(pending_comment) if pending_comment else None
                pending_comment = []
                stack.append({
                    "kind": "service", "name": m.group(1), "depth": depth, "methods": [],
                    "line_start": lineno, "comment": comment,
                })
            elif (m := _RPC.match(line)) and stack and stack[-1]["kind"] == "service":
                comment = "\n".join(pending_comment) if pending_comment else None
                pending_comment = []
                stack[-1]["methods"].append(ProtoMethod(
                    name=m.group(1),
                    input_type=m.group(3),
                    output_type=m.group(5),
                    client_streaming=bool(m.group(2)),
                    server_streaming=bool(m.group(4)),
                    line=lineno,
                    comment=comment,
                    needs_ai=comment is None,
                ))
            elif (m := _MAP_FIELD.match(line)) and stack and stack[-1]["kind"] == "message":
                pending_comment = []
                stack[-1]["fields"].append(ProtoField(
                    name=m.group(3),
                    type=f"map<{m.group(1)},{m.group(2)}>",
                    number=int(m.group(4)),
                    label="optional",
                ))
            elif (m := _FIELD.match(line)) and stack and stack[-1]["kind"] == "message":
                pending_comment = []
                label_raw = (m.group(1) or "").strip()
                label = "repeated" if label_raw == "repeated" else (
                    "required" if label_raw == "required" else "optional"
                )
                stack[-1]["fields"].append(ProtoField(
                    name=m.group(3),
                    type=m.group(2),
                    number=int(m.group(4)),
                    label=label,
                ))
            elif _CLOSE.match(line) and stack and depth < stack[-1]["depth"]:
                pending_comment = []
                frame = stack.pop()
                if frame["kind"] == "message":
                    messages.append(ProtoMessage(
                        name=frame["name"], fields=frame["fields"], file_path=path,
                        line_start=frame["line_start"], line_end=lineno,
                        comment=frame["comment"], needs_ai=frame["comment"] is None,
                    ))
                elif frame["kind"] == "service":
                    services.append(ProtoService(
                        name=frame["name"],
                        methods=frame["methods"],
                        file_path=path,
                        line_start=frame["line_start"],
                        line_end=lineno,
                        comment=frame["comment"],
                        needs_ai=frame["comment"] is None,
                    ))
            else:
                pending_comment = []

        return services, messages
