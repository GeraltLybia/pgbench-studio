# pgbench studio

Веб-интерфейс для нагрузочного тестирования PostgreSQL через pgbench: профили подключения, настройка нагрузки и сценариев с проверкой SQL, запуск с прогресс-баром и живыми логами, отчёт с графиками, история и сравнение запусков.

## Источники правды

- `docs/architecture.md` — утверждённый документ «pgbench studio — архитектура и план реализации». Это главный источник требований. При расхождении с этим файлом прав документ.
- `docs/design/pgbench_UI_light.pdf`, `docs/design/pgbench_UI_dark.pdf` — макеты экранов (светлая и тёмная тема), экспорт с холста.
- `docs/PLAN.md` — рабочая детализация этапов и принятые трактовки документа.
- `docs/design/tokens.css` — цвета, шрифты и радиусы из макетов.

Если чего-то нет в документе и макетах — не придумывай, спроси.

## Ключевые решения (кратко)

- Стек: бэкенд Python 3.12 + FastAPI + pydantic v2 + SQLite (SQLAlchemy 2, Alembic); фронтенд Vue 3 + TypeScript + Vite + Pinia + zod + ECharts + CodeMirror 6.
- Развёртывание: два контейнера на одной машине — `frontend` (nginx + SPA, проксирует `/api` и WebSocket) и `backend` (FastAPI + pgbench 18). HTTPS терминируется на корпоративном балансировщике перед машиной.
- Один pgbench 18 на агенте, поддерживаемые серверы PostgreSQL 13–18.
- Мониторинг ресурсов только машины-агента (psutil). Мониторинга сервера БД нет.
- Роли: `viewer`, `editor`, `admin`. Пользователями управляет `admin` из интерфейса.
- Пароли профилей БД хранятся зашифрованными (Fernet), пароли пользователей — argon2id.

## Правила работы

- Работаем строго по этапам из раздела «План реализации» документа: один этап за раз. Этап закончен, когда выполнены все его критерии приёмки. Не реализуй функциональность следующих этапов заранее.
- Unit-тесты бэкенда пишутся вместе с кодом, не после. Порог покрытия: 85 % для `backend/app/core` и `backend/app/api`, 70 % для остального.
- Перед тем как сказать «готово», запусти линтеры и тесты и приложи результат.
- Любая проверка, которую делает фронт (лимиты нагрузки, правила опасного SQL, права по ролям), обязательно дублируется на бэкенде.

## Безопасность (не нарушать)

- pgbench запускается только через `asyncio.create_subprocess_exec` со списком аргументов. Никогда `shell=True`.
- Пароль БД передаётся только через env `PGPASSWORD` дочернего процесса. Его нет в argv, логах, ответах API и WebSocket.
- Изменяющие эндпоинты проверяют роль на бэкенде.
- `\shell` и `\setshell` в сценариях запрещены.

## Соглашения

- Код, идентификаторы и комментарии в коде — на английском. Тексты интерфейса и документация — на русском.
- Бэкенд: `uv`, `ruff`, `mypy --strict` для `app/`, `pytest` + `pytest-asyncio`.
- Фронтенд: `pnpm`, ESLint, `vue-tsc`, Vitest, Playwright.
- Типы API на фронте генерируются из OpenAPI (`openapi-typescript`), руками не правятся.

## Команды

Бэкенд (из `backend/`):

- установка: `uv sync`
- проверки: `uv run ruff check . && uv run ruff format --check . && uv run mypy app`
- тесты с порогами покрытия: `uv run pytest --cov=app --cov-report=json && uv run python scripts/check_coverage.py`
- интеграционные тесты (Docker + pgbench 18, PostgreSQL 13 и 18 в Testcontainers): `uv run pytest -m integration`; путь к pgbench 18 — `PGBENCH_BINARY` (на macOS: `brew install postgresql@18`, бинарник `/opt/homebrew/opt/postgresql@18/bin/pgbench`)
- запуск локально: `PGB_STUDIO_SECRET_KEY=$(uv run studio gen-key) uv run studio --config <config.yaml> serve` (для локального HTTP нужен `server.dev_mode: true`)
- ключ шифрования: `uv run studio gen-key`; схема OpenAPI: `uv run studio openapi -o ../frontend/openapi.json`
- аварийный доступ: `studio users reset-admin [--username NAME]`
- образ: `docker build -t pgbench-studio-backend backend`

Фронтенд (из `frontend/`):

- установка: `pnpm install`
- dev-сервер: `pnpm dev` (http://localhost:5173, проксирует `/api` на бэкенд `127.0.0.1:8000`, адрес меняется через `PGB_STUDIO_BACKEND`)
- проверки: `pnpm lint && pnpm typecheck && pnpm test`
- типы API из OpenAPI бэкенда: `pnpm gen:api` (обновляет `openapi.json` и `src/types/api.ts`, руками не править)
- сборка: `pnpm build`

Docker compose (из корня):

- первый запуск: `cp config.example.yaml config.yaml && cp .env.example .env`, в `.env` задать `PGB_STUDIO_SECRET_KEY` (`studio gen-key`) и пароль первого админа; для локального HTTP в `config.yaml` — `server.dev_mode: true`, `auth.cookie_secure: false`
- запуск: `docker compose up -d --build`, состояние: `docker compose ps` (все `healthy`), приложение — http://localhost:8080
- тестовые базы внутри сети compose: `pg13:5432` и `pg18:5432`, пользователь и база `bench`, пароль `PGB_TEST_DB_PASSWORD` (по умолчанию `bench`)
- аварийный доступ: `docker compose exec backend studio users reset-admin`
