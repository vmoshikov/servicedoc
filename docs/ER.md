<!-- @ai:document type="er_diagram" service="servicedoc" lang="ru" -->
# Внутренние модели данных — servicedoc

> servicedoc не использует внешнюю БД. Ниже описаны основные Pydantic-модели,
> которые образуют внутреннюю схему данных сервиса.

<!-- @ai:section type="er_diagram" format="plantuml" -->
```plantuml
@startuml
!theme plain

entity "PipelineContext" {
  * repo_config : RepoConfig <<root>>
  --
  work_dir : Path
  output_dir : Path
  local_repo_path : Path
  detected_language : string
  all_source_files : list[Path]
  symbols : list[Symbol]
  external_deps : list[ExternalDep]
  proto_services : list[ProtoService]
  er_entities : list[EREntity]
  er_relations : list[ERRelation]
  er_diagram : string
  coverage_result : CoverageResult
  git_history : list[ChangelogEntry]
  git_tags : list[string]
}

entity "Symbol" {
  * name : string <<PK>>
  --
  kind : string
  file_path : Path
  line_start : int
  line_end : int
  is_public : bool
  comment : string
  ai_description : string
  needs_ai : bool
}

entity "FunctionSymbol" {
  --
  parameters : list[Parameter]
  return_types : list[TypeRef]
  receiver : string
}

entity "ClassSymbol" {
  --
  methods : list[FunctionSymbol]
  fields : list[Parameter]
  base_classes : list[string]
  decorators : list[string]
}

entity "EREntity" {
  * name : string <<PK>>
  --
  table_name : string
  fields : list[ERField]
  source_file : Path
  orm_type : string
}

entity "ProtoService" {
  * name : string <<PK>>
  --
  methods : list[ProtoMethod]
  file_path : Path
}

entity "CoverageResult" {
  * report_source : string <<PK>>
  --
  overall_pct : float
  covered_lines : int
  total_lines : int
  test_files : list[TestFile]
}

entity "StageResult" {
  * stage_name : string <<PK>>
  --
  success : bool
  errors : list[string]
  warnings : list[string]
  duration_seconds : float
}

"PipelineContext" ||--o{ "Symbol" : "contains"
"PipelineContext" ||--o{ "EREntity" : "contains"
"PipelineContext" ||--o{ "ProtoService" : "contains"
"PipelineContext" ||--|| "CoverageResult" : "has"
"PipelineContext" ||--o{ "StageResult" : "tracks"
"Symbol" ||--|| "FunctionSymbol" : "extends"
"Symbol" ||--|| "ClassSymbol" : "extends"
@enduml
```
<!-- @ai:end -->

## Описание моделей

<!-- @ai:section type="table_description" id="PipelineContext" -->
### PipelineContext

Центральный контейнер состояния. Создаётся `PipelineRunner` в начале запуска
и передаётся каждому этапу. Каждый этап мутирует контекст — добавляет символы,
ER-сущности, proto-сервисы и т.д.

**Источник:** `servicedoc/models/pipeline.py`
<!-- @ai:end -->

<!-- @ai:section type="table_description" id="Symbol" -->
### Symbol / FunctionSymbol / ClassSymbol

Иерархия публичных символов кода. `Symbol` — абстрактный базовый класс.
`needs_ai=True` устанавливается в s05_comments если комментарий отсутствует.
`ai_description` заполняется в s06_ai_enrich.

**Источник:** `servicedoc/models/symbols.py`
<!-- @ai:end -->

<!-- @ai:section type="table_description" id="EREntity" -->
### EREntity / ERRelation

Модели для построения ER-диаграммы. Наполняются в s08_er детекторами
`GoGORMDetector`, `PySQLAlchemyDetector`, `RawSQLDetector`.
`is_inferred=True` для таблиц обнаруженных из raw SQL (менее надёжно).

**Источник:** `servicedoc/models/er.py`
<!-- @ai:end -->
<!-- @ai:end -->
