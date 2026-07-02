<!-- @ai:document type="configuration" service="servicedoc" lang="ru" -->
# Конфигурация — servicedoc

Конфигурация через `.env` файл или переменные окружения. Вложенные секции разделяются `__`.

## Переменные окружения

<!-- @ai:section type="config_section" id="ai" -->
### AI (OpenAI-compatible endpoint)

| Переменная | По умолчанию | Описание |
|---|---|---|
| `AI__BASE_URL` | **обязательно** | Базовый URL API (напр. `https://api.openai.com`) |
| `AI__API_KEY` | `""` | API ключ (Bearer token) |
| `AI__MODEL` | `gpt-4o` | Имя модели |
| `AI__MAX_TOKENS` | `2048` | Максимум токенов в ответе |
| `AI__BATCH_SIZE` | `10` | Символов в одном AI-запросе |
| `AI__RATE_LIMIT_RPM` | `60` | Запросов в минуту (rate limit) |
| `AI__RETRY_MAX_ATTEMPTS` | `5` | Попыток при 429/503 |
| `AI__RETRY_BASE_DELAY_SECONDS` | `2.0` | Базовая задержка backoff (секунды) |
<!-- @ai:end -->

<!-- @ai:section type="config_section" id="git" -->
### Git

| Переменная | По умолчанию | Описание |
|---|---|---|
| `GIT__GITHUB_TOKEN` | `null` | GitHub personal access token |
| `GIT__GITLAB_TOKEN` | `null` | GitLab personal access token (oauth2) |
| `GIT__CLONE_TIMEOUT_SECONDS` | `120` | Таймаут клонирования репозитория |
<!-- @ai:end -->

<!-- @ai:section type="config_section" id="cache" -->
### Кэш

| Переменная | По умолчанию | Описание |
|---|---|---|
| `CACHE__CACHE_DIR` | `/tmp/servicedoc_cache` | Директория кэша (клоны + AI-ответы) |
| `CACHE__CLONE_CACHE_TTL_SECONDS` | `86400` | TTL клонов (0 = всегда перекачивать) |
| `CACHE__AI_RESPONSE_CACHE` | `true` | Кэшировать AI-ответы по хешу промпта |
<!-- @ai:end -->

<!-- @ai:section type="config_section" id="general" -->
### Общие

| Переменная | По умолчанию | Описание |
|---|---|---|
| `OUTPUT_DIR` | `./servicedoc_output` | Директория генерируемой документации |
| `MAX_CONCURRENT_PARSERS` | `8` | Параллельных парсеров файлов (asyncio.Semaphore) |
| `MAX_CONCURRENT_AI_CALLS` | `3` | Параллельных AI-запросов |
| `REPORT_LANGUAGE` | `ru` | Язык генерируемой документации |
<!-- @ai:end -->

## Пример .env файла

<!-- @ai:section type="config_example" -->
```bash
# AI (обязательно)
AI__BASE_URL=https://api.openai.com
AI__API_KEY=sk-proj-...
AI__MODEL=gpt-4o
AI__BATCH_SIZE=10
AI__RATE_LIMIT_RPM=60

# Токены git (для приватных репозиториев)
GIT__GITHUB_TOKEN=ghp_...
GIT__GITLAB_TOKEN=glpat-...

# Кэш
CACHE__CACHE_DIR=/var/cache/servicedoc
CACHE__CLONE_CACHE_TTL_SECONDS=3600

# Вывод
OUTPUT_DIR=/var/www/docs
MAX_CONCURRENT_PARSERS=8
MAX_CONCURRENT_AI_CALLS=3
```
<!-- @ai:end -->

## Пропуск этапов

<!-- @ai:section type="skip_stages" -->
Для пропуска конкретных этапов используйте `--skip` или `SKIP_STAGES`:

| Этап | Когда пропускать |
|---|---|
| `s02_deps` | Нет внешних git-зависимостей |
| `s04_proto` | Нет .proto файлов |
| `s06_ai_enrich` | AI API недоступен или не нужен |
| `s07_tests` | Нет coverage-отчётов |
| `s08_er` | Нет БД в сервисе |

```bash
servicedoc analyze <URL> --skip s06_ai_enrich --skip s08_er
```
<!-- @ai:end -->
<!-- @ai:end -->
