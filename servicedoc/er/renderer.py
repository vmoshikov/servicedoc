from servicedoc.models.er import EREntity, ERFieldKind, ERRelation

_ARROWS = {
    "one_to_one": "||--||",
    "one_to_many": "||--o{",
    "many_to_many": "}o--o{",
}


class PlantUMLRenderer:
    def render(self, entities: list[EREntity], relations: list[ERRelation]) -> str:
        lines = ["@startuml", "!theme plain", ""]

        for ent in entities:
            lines.append(f'entity "{ent.effective_table_name}" {{')
            pks = [f for f in ent.fields if f.kind == ERFieldKind.PK]
            rest = [f for f in ent.fields if f.kind != ERFieldKind.PK]
            for f in pks:
                nullable = "" if not f.nullable else ""
                lines.append(f"  * {f.name} : {f.type} <<PK>>")
            if pks and rest:
                lines.append("  --")
            for f in rest:
                marker = " <<FK>>" if f.kind == ERFieldKind.FK else ""
                required = "* " if not f.nullable else "  "
                lines.append(f"{required}{f.name} : {f.type}{marker}")
            lines.append("}")
            lines.append("")

        seen: set[tuple[str, str]] = set()
        for rel in relations:
            key = (rel.from_entity, rel.to_entity)
            if key in seen:
                continue
            seen.add(key)
            arrow = _ARROWS.get(rel.kind, "||--o{")
            style = ".." if rel.is_inferred else "--"
            arrow = arrow.replace("--", style)
            label = f' : "{rel.label}"' if rel.label else ""
            lines.append(f'"{rel.from_entity}" {arrow} "{rel.to_entity}"{label}')

        lines.append("")
        lines.append("@enduml")
        return "\n".join(lines)
