from __future__ import annotations

import re
from abc import ABC, abstractmethod
from pathlib import Path

import tree_sitter_go as tsg
import tree_sitter_python as tsp
from tree_sitter import Language, Node, Parser, Query, QueryCursor

from servicedoc.models.er import EREntity, ERField, ERFieldKind, ERRelation

GO_LANGUAGE = Language(tsg.language())
PY_LANGUAGE = Language(tsp.language())
_GO_PARSER = Parser(GO_LANGUAGE)
_PY_PARSER = Parser(PY_LANGUAGE)


def _node_text(node: Node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


class ORMDetector(ABC):
    @abstractmethod
    def detect(
        self, source: bytes, path: Path
    ) -> tuple[list[EREntity], list[ERRelation]]:
        ...


class GoGORMDetector(ORMDetector):
    _GORM_TAG = re.compile(r'gorm:"([^"]*)"')
    _FK_TAG = re.compile(r"foreignKey:(\w+)")
    _TABLE_TAG = re.compile(r'column:"([^"]*)"')

    def detect(self, source: bytes, path: Path) -> tuple[list[EREntity], list[ERRelation]]:
        tree = _GO_PARSER.parse(source)
        entities: list[EREntity] = []
        relations: list[ERRelation] = []

        struct_query = Query(GO_LANGUAGE, """
        (type_declaration
          (type_spec
            name: (type_identifier) @struct.name
            type: (struct_type
              (field_declaration_list) @struct.fields)))
        """)

        for match in QueryCursor(struct_query).matches(tree.root_node):
            cap = match[1]
            name_nodes = cap.get("struct.name", [])
            fields_nodes = cap.get("struct.fields", [])
            if not name_nodes or not fields_nodes:
                continue
            struct_name = _node_text(name_nodes[0], source)
            if not struct_name[0].isupper():
                continue

            fields_node = fields_nodes[0]
            er_fields: list[ERField] = []
            has_gorm = False

            for field_decl in fields_node.children:
                if field_decl.type != "field_declaration":
                    continue
                tag_node = next((c for c in field_decl.children if c.type == "raw_string_literal"), None)
                if tag_node:
                    tag_text = _node_text(tag_node, source)
                    if "gorm:" in tag_text:
                        has_gorm = True
                        # detect primary key
                        gorm_m = self._GORM_TAG.search(tag_text)
                        gorm_attrs = gorm_m.group(1) if gorm_m else ""
                        kind = ERFieldKind.PK if "primaryKey" in gorm_attrs else ERFieldKind.FIELD

                        name_list = [c for c in field_decl.children if c.type == "field_identifier_list"]
                        type_nodes = [c for c in field_decl.children if c.type not in (
                            "field_identifier_list", "raw_string_literal", "comment"
                        )]
                        field_name = _node_text(name_list[0], source) if name_list else "unknown"
                        field_type = _node_text(type_nodes[-1], source) if type_nodes else "unknown"
                        er_fields.append(ERField(name=field_name, type=field_type, kind=kind))

                        # detect FK relation
                        fk_m = self._FK_TAG.search(tag_text)
                        if fk_m:
                            related = field_name.replace("ID", "").replace("Id", "")
                            relations.append(ERRelation(
                                from_entity=struct_name,
                                to_entity=related,
                                kind="many_to_one" if False else "one_to_many",  # type: ignore
                                label="",
                            ))

            if has_gorm:
                entities.append(EREntity(
                    name=struct_name,
                    fields=er_fields,
                    source_file=path,
                    orm_type="gorm",
                ))

        return entities, relations


class PySQLAlchemyDetector(ORMDetector):
    _BASE_NAMES = frozenset({"Base", "DeclarativeBase", "MappedAsDataclass", "Model"})
    _FK_RE = re.compile(r'ForeignKey\(["\']([^"\']+)["\']')

    def detect(self, source: bytes, path: Path) -> tuple[list[EREntity], list[ERRelation]]:
        tree = _PY_PARSER.parse(source)
        entities: list[EREntity] = []
        relations: list[ERRelation] = []

        class_query = Query(PY_LANGUAGE, """
        (class_definition
          name: (identifier) @class.name
          superclasses: (argument_list)? @class.bases
          body: (block) @class.body)
        """)

        for match in QueryCursor(class_query).matches(tree.root_node):
            cap = match[1]
            name_nodes = cap.get("class.name", [])
            bases_nodes = cap.get("class.bases", [])
            body_nodes = cap.get("class.body", [])
            if not name_nodes:
                continue

            class_name = _node_text(name_nodes[0], source)
            if bases_nodes:
                base_text = _node_text(bases_nodes[0], source)
                if not any(b in base_text for b in self._BASE_NAMES):
                    continue
            else:
                continue

            er_fields: list[ERField] = []
            if body_nodes:
                body_text = _node_text(body_nodes[0], source)
                # detect Column(ForeignKey(...))
                for fk_m in self._FK_RE.finditer(body_text):
                    ref = fk_m.group(1).split(".")[0]
                    relations.append(ERRelation(
                        from_entity=class_name,
                        to_entity=ref.capitalize(),
                        kind="one_to_many",
                        label="FK",
                    ))

            entities.append(EREntity(
                name=class_name,
                fields=er_fields,
                source_file=path,
                orm_type="sqlalchemy",
            ))

        return entities, relations


class RawSQLDetector(ORMDetector):
    _TABLE_RE = re.compile(
        r"\b(?:FROM|JOIN|INSERT\s+INTO|UPDATE)\s+[`\"\']?(\w+)[`\"\']?",
        re.IGNORECASE,
    )

    def detect(self, source: bytes, path: Path) -> tuple[list[EREntity], list[ERRelation]]:
        text = source.decode("utf-8", errors="replace")
        entities: list[EREntity] = []
        seen: set[str] = set()
        for m in self._TABLE_RE.finditer(text):
            table = m.group(1)
            if table.upper() in ("SELECT", "WHERE", "SET", "NULL") or table in seen:
                continue
            seen.add(table)
            entities.append(EREntity(
                name=table.capitalize(),
                table_name=table,
                source_file=path,
                orm_type="raw_sql",
            ))
        return entities, []
