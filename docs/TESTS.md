<!-- @ai:document type="test_report" service="servicedoc" lang="ru" -->
# Тесты — servicedoc

## Покрытие

<!-- @ai:section type="coverage_summary" -->
| Метрика | Значение |
|---|---|
| Unit-тестов | 21 |
| Тестовых файлов | 5 |
| Статус | ✅ все проходят |
<!-- @ai:end -->

## Запуск тестов

```bash
# Установка с dev зависимостями
pip install -e ".[dev]"

# Unit тесты (быстро, без внешних сервисов)
pytest tests/unit/ -v

# С покрытием
pytest tests/unit/ --cov=servicedoc --cov-report=html
```

## Тестовые файлы

<!-- @ai:section type="test_files" -->
| Файл | Что тестирует |
|---|---|
| `tests/unit/test_go_parser.py` | GoParser: экспорт функций, комментарии, приватные символы |
| `tests/unit/test_python_parser.py` | PythonParser: docstrings, классы, публичные символы |
| `tests/unit/test_proto_parser.py` | ProtoFileParser: сервисы, методы, streaming, поля сообщений |
| `tests/unit/test_er_detector.py` | GoGORMDetector, PySQLAlchemyDetector, RawSQLDetector |
| `tests/unit/test_changelog_dedup.py` | Дедупликация коммитов, группировка по типу |
<!-- @ai:end -->

## Тестовые фикстуры

<!-- @ai:section type="fixtures" -->
### tests/fixtures/sample_go/

Минимальный Go-сервис для проверки парсера:
- `main.go` — функции с комментариями (`GetUser`, `CreateUser`, `DeleteUser`)
- `model.go` — GORM-структуры (`User`, `Post`) с тегами `gorm:`
- `service.proto` — proto-файл с `UserService` (4 метода, включая streaming)
- `go.mod` — зависимости (gin, gorm, postgres)

### tests/fixtures/sample_python/

Python-сервис для проверки Python-парсера:
- `main.py` — FastAPI функции с docstrings (`get_user`, `create_user`)
- `models.py` — SQLAlchemy модели с `DeclarativeBase`, ForeignKey
- `pyproject.toml` — зависимости проекта

### conftest.py

- `go_fixture_repo` — копирует sample_go в tmp_path + `git init` + `git tag v0.1.0`
- `go_fixture_path`, `python_fixture_path` — пути к fixture директориям
<!-- @ai:end -->

## Mock стратегия

<!-- @ai:section type="mocks" -->
Для изоляции AI-вызовов в интеграционных тестах используется `respx` (httpx mock):

```python
import respx
import httpx

@pytest.mark.asyncio
async def test_ai_client_retry_on_429():
    with respx.mock:
        # первый запрос — 429
        respx.post("/v1/chat/completions").mock(
            side_effect=[
                httpx.Response(429),
                httpx.Response(200, json={"choices": [{"message": {"content": '["desc"]'}}]})
            ]
        )
        client = AIClient(config)
        result = await client.complete("system", "user")
        assert result == '["desc"]'
```
<!-- @ai:end -->
<!-- @ai:end -->
