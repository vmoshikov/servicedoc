<!-- @ai:document type="changelog" service="servicedoc" lang="ru" -->
# CHANGELOG — servicedoc

Все значимые изменения фиксируются в этом файле.
Формат: [Keep a Changelog](https://keepachangelog.com/ru/1.0.0/).

## [0.1.0] — 2026-07-02

<!-- @ai:section type="release" id="v0.1.0" -->

### Новые возможности

- Анализ Go-репозиториев через tree-sitter (публичные функции, методы, структуры)
- Анализ Python-репозиториев через tree-sitter (функции, классы, docstrings)
- Клонирование внешних git-зависимостей с импортным фильтром (только используемые файлы)
- Парсинг .proto файлов (stdlib re) → JSON-схемы ProtoService/ProtoMessage
- Извлечение комментариев разработчика (Go `//`, Python docstrings, `#`)
- AI-обогащение символов без комментариев (OpenAI-compatible `/v1/chat/completions`)
- Rate limiting через TokenBucketRateLimiter + exponential backoff retry
- Парсинг существующих coverage-отчётов (coverage.xml, .coverage, lcov.info, coverage.out)
- Детектирование ER-сущностей: GORM, SQLAlchemy, raw SQL
- Генерация PlantUML ER-диаграмм (нет внешних зависимостей)
- Дедупликация коммитов через character-level `difflib.SequenceMatcher` (threshold 0.75)
- Генерация CHANGELOG с группировкой по типу коммита (feat/fix/refactor/chore/breaking)
- Генерация RELEASE_NOTES per tag с AI-анализом diff
- Jinja2-шаблоны документации на русском языке с ai-ready разметкой `<!-- @ai:* -->`
- CLI интерфейс (`servicedoc analyze`, `servicedoc serve`) через typer
- Опциональный REST API (FastAPI, `servicedoc[api]`)

### Технические детали

- Python 3.12+, 9 core зависимостей
- tree-sitter 0.26 API (QueryCursor + Query вместо Language.query)
- Stdlib retry (asyncio), cache (shelve+hashlib), proto parser (re), changelog dedup (difflib)
- 21 unit-тест (pytest-asyncio)

<!-- @ai:end -->
<!-- @ai:end -->
