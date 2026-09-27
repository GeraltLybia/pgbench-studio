# План работ pgbench studio

Рабочая детализация раздела «План реализации» из [architecture.md](architecture.md). При расхождении прав документ архитектуры. Этапы идут строго по очереди: следующий начинается, когда закрыты все критерии приёмки текущего.

Общий критерий каждого этапа: unit-тесты бэкенда пишутся вместе с кодом, покрытие ≥ 85 % для `backend/app/core` и `backend/app/api`, ≥ 70 % для остального; ruff, mypy --strict, pytest, ESLint, vue-tsc, Vitest — зелёные.

## Принятые трактовки документа

- В разделе «Цель и границы MVP» сказано «без ролей», но раздел «Роли и доступ» и этап 0 требуют ролей `viewer` / `editor` / `admin` — реализуем роли.
- «Изменяющие запросы доступны только роли `editor`» читается как «`editor` и выше»: `admin` может всё, что `editor`.
- Макеты лежат в `docs/design/*.pdf` (перенесены из `design/`), документ архитектуры — `docs/architecture.md`.

## Статус (обновлено 2026-09-27)

Этап 0 в работе.

Готово — бэкенд (`backend/`):

- конфиг (`config.yaml` + env `PGB_STUDIO_*`, понятная ошибка и код выхода 2), JSON-логи;
- SQLite + Alembic (`users`, `sessions`), миграции применяются при старте;
- вход/выход/`me`/смена пароля, блокировка по логину и по реальному IP, обязательная смена временного пароля;
- управление пользователями для `admin` (создание с временным паролем, роль, блокировка, сброс пароля, защита последнего `admin`);
- отказ изменяющих запросов не по HTTPS вне dev-режима, uvicorn с `--proxy-headers` и `FORWARDED_ALLOW_IPS`;
- `/healthz`, `/readyz` (кеш 5 с), `/api/system/health`, `/api/system/info`;
- CLI `studio serve | gen-key | openapi | users reset-admin`;
- 120 unit-тестов, покрытие ~99 % (`app/api`, `app/core`, прочее), ruff и mypy --strict чистые;
- `backend/Dockerfile`: образ собирается, pgbench 18.6, контейнер проходит healthcheck.

Начато — фронтенд (`frontend/`): `package.json` с зависимостями, конфиги Vite / TS / ESLint, `tokens.css`. TypeScript закреплён на 6.0.x: vue-tsc 3.3 не работает с TypeScript 7.

Осталось в этапе 0, по порядку:

1. Фронтенд: `main.ts`, `App.vue`, `base.css`, шрифты; `api/http.ts`, `api/auth.ts`, `api/users.ts`, `api/system.ts`; генерация `src/types/api.ts` (`pnpm gen:api`).
2. Сторы `auth` (`can()`), `system`; роутер и guard-ы (вход, роль, обязательная смена пароля).
3. Оболочка: `AppSidebar` (меню, индикатор состояния со списком проверок, переключатель темы, меню пользователя), `PageHeader`.
4. Экраны: `LoginView` (по макету, с ошибкой и числом оставшихся попыток), `ChangePasswordView`, `UsersView`, пустые экраны Подключение / Нагрузка / Выполнение / Отчёт / История / Сравнение.
5. Vitest: `can()`, guard-ы, http-обёртка (401/403), тема, форма входа; ESLint и vue-tsc чистые.
6. `frontend/Dockerfile`, `frontend/nginx.conf` (прокси `/api` и WS, `/healthz`, `set_real_ip_from` для `trusted_proxies`, `X-Forwarded-Proto` только от балансировщика, таймаут WS ≥ `max_duration_s`).
7. `docker-compose.yml`: `backend`, `frontend` (8080, после healthy `backend`, фиксированный IP для `FORWARDED_ALLOW_IPS`), `pg13`, `pg18`; тома `./data`, `./config.yaml:ro`; `.env`.
8. `.github/workflows/ci.yml`: ruff, mypy, pytest + `check_coverage.py`, ESLint, vue-tsc, Vitest, актуальность `api.ts`, сборка образов.
9. Проверка всех критериев этапа 0 (`docker compose ps` — healthy, браузер в обеих темах), дописать «Команды» в CLAUDE.md, PR `stage-0` → `main`.

Замечания к документу, которые надо подтвердить:

- В Debian/PGDG pgbench входит не в `postgresql-client-18`, а в серверный пакет `postgresql-18`. В образе ставится клиент, а из серверного пакета извлекается только бинарник pgbench, сам сервер не устанавливается.
- Этап 1 говорит «пароль не хранится, если ключа нет», а разделы «Модель данных» и «Роли» — «без ключа бэкенд не стартует». Сейчас сделано второе: без ключа старт запрещён.
- `/readyz` дополнительно отдаёт `pgbench_version`, чтобы на экране входа была подпись «pgbench 18» (как в макете) без сессии.
- Минимальная длина нового пароля — 8 символов; админ создаёт пользователя, пароль генерируется сервером и показывается один раз.
- Проверку «Зависшие запуски» добавим в этапе 3 вместе с таблицей `runs`.

## Этап 0. Каркас

Бэкенд (`backend/`, uv):

- `pyproject.toml`: FastAPI, uvicorn, pydantic v2, pydantic-settings, PyYAML, SQLAlchemy 2 + aiosqlite, Alembic, argon2-cffi, cryptography, psutil; dev — ruff, mypy, pytest, pytest-asyncio, pytest-cov, httpx.
- `app/config.py` — модели настроек, загрузка `config.yaml` (`PGB_STUDIO_CONFIG`), переопределение `PGB_STUDIO_<SECTION>__<FIELD>`, понятная ошибка и отказ старта.
- `app/storage/` — `db.py` (движок, сессии), `models.py` (`users`, `sessions`), Alembic-миграция `0001`.
- `app/security/passwords.py` (argon2id), `sessions.py` (токен в cookie, в БД только хеш).
- `app/api/deps.py` — текущий пользователь, `require_role`; проверка `X-Forwarded-Proto: https` для изменяющих запросов вне dev-режима.
- `app/api/auth.py` — вход с блокировкой по логину и реальному IP, выход, `me`, смена пароля; обязательная смена временного пароля.
- `app/api/users.py` — управление пользователями для `admin`, защита последнего активного `admin`, запрет понизить себя.
- `app/api/health.py` + `app/core/healthchecks.py` — `/healthz`, `/readyz` (кеш 5 с), `/api/system/health`.
- `app/api/system.py` — версии приложения и pgbench, имя агента, лимиты.
- `app/cli.py` — `studio users reset-admin`.
- Первый `admin` из `PGB_STUDIO_ADMIN_USER` / `PGB_STUDIO_ADMIN_PASSWORD`, JSON-логи в stdout.
- Тесты: конфиг, пароли, сессии, матрица прав по всем эндпоинтам, блокировка входа, управление пользователями, health-проверки (ok / warning / fail), CLI.

Фронтенд (`frontend/`, pnpm):

- Vite + Vue 3 + TS, Pinia, Vue Router, VueUse, zod, шрифты через `@fontsource`.
- `styles/tokens.css` из `docs/design/tokens.css`, `base.css`; тема по `prefers-color-scheme`, выбор запоминается.
- Оболочка: `AppSidebar` (пункты меню, индикатор состояния системы со списком проверок, переключатель темы, меню пользователя), `PageHeader`.
- Экраны: вход (по макету), смена пароля, «Пользователи» для `admin`, пустые экраны Подключение / Нагрузка / Выполнение / Отчёт / История / Сравнение.
- `api/http.ts` (401 → `/login`, 403), `stores/auth.ts` (`can()`), `stores/system.ts`, guard-ы входа и роли.
- Типы API из OpenAPI (`openapi-typescript`), скрипт генерации и проверка актуальности в CI.
- Vitest: `can()`, guard-ы, http-обёртка, тема, форма входа.

Инфраструктура:

- `backend/Dockerfile` (python:3.12-slim + `postgresql-client-18` из PGDG, `PG_MAJOR=18`), `frontend/Dockerfile` (сборка + nginx:alpine), `frontend/nginx.conf` (статика, `/api` и WS на `backend:8000`, `/healthz`, доверие `X-Forwarded-*` только от `trusted_proxies`, таймаут WS ≥ `max_duration_s`).
- `docker-compose.yml`: `backend`, `frontend` (8080 наружу, старт после healthy `backend`), тестовые `pg13` и `pg18`; тома `./data`, `./config.yaml:ro`; секреты из `.env`.
- `config.example.yaml`, `.env.example`.
- `.github/workflows/ci.yml`: ruff, mypy, pytest + пороги покрытия, ESLint, vue-tsc, Vitest, актуальность типов API, сборка образов.

Проверка критериев:

| Критерий | Как проверяется |
| --- | --- |
| compose поднимает агент и PG 13/18 | `docker compose up -d`, `docker compose ps` — все `healthy` |
| healthcheck, `/healthz`, `/readyz`, индикатор | curl через `localhost:8080`, индикатор в меню |
| вход `editor` / `viewer`, 403 | unit-тесты матрицы прав, ручная проверка в браузере |
| управление пользователями | unit-тесты + сценарий в интерфейсе |
| балансировщик | локально — эмуляция заголовков `X-Forwarded-*` curl-ом; полностью — только на стенде с балансировщиком инфраструктуры |
| `localhost:8080`, меню, тема | браузер, обе темы |
| ошибка в `config.yaml` | запуск с битым конфигом, текст ошибки |
| CI | workflow на GitHub |

## Этап 1. Подключение

- `profiles` (миграция), `storage/crypto.py` (Fernet), CRUD `/api/profiles`, пароль не возвращается в API.
- `POST /api/profiles/test` через psycopg 3: версия сервера, совместимость с pgbench, `max_connections` и свободные, время отклика, таблицы `pgbench_*`, примерный scale; классификатор ошибок по таблице кодов.
- `POST /api/profiles/{id}/init` — `pgbench -i` с подтверждением вводом имени базы; минимальный раннер для `kind=init` и разбор `N of M tuples (x%) done`.
- Фронт: `ConnectView` по макету (успех / ошибка), `ProfileSelect`, `ProfileForm`, `ConnectionCheck`, `InitPanel`, `ConfirmByTyping`; `useProfilesStore` с хешем параметров; guard «нет успешной проверки → `/connect`»; автопроверка сохранённого профиля.
- Интеграционные тесты (Testcontainers): pgbench 18 против PostgreSQL 13 и 18.

## Этап 2. Нагрузка и валидатор

- `RunConfig` (pydantic) и zod-схема, `core/limits.py`, `core/command.py`, `POST /api/runs/preview` с маской пароля.
- `core/validator.py` + `core/safety.py` (pglast, версии узлов AST, уровни правил), `POST /api/scripts/validate`, `/api/scripts` CRUD, `/api/builtins`.
- `POST /api/runs/dry` (`-c 1 -t 1 -n`), `422` при нарушении лимитов и правил в обход фронта.
- Фронт: `LoadView`, `LoadParams`, `ScenarioList` (веса, перетаскивание), `ScriptEditor` (CodeMirror 6, подсветка мета-команд, lint через 400 мс), `CommandPreview`, `PreRunSummary` с подтверждением «опасных» правил; черновик в `localStorage`.

## Этап 3. Запуск и живой мониторинг

- `core/runner.py` (RunManager, `create_subprocess_exec`, `PGPASSWORD` в env, отмена SIGINT → SIGTERM → SIGKILL, восстановление после рестарта), `core/events.py` (кольцевой буфер), `metrics/agent.py` (psutil), `parsers/progress.py`.
- `POST /api/runs` (`409` при занятом агенте), `POST /api/runs/{id}/cancel`, WebSocket `/api/runs/{id}/ws` со `snapshot`, проверкой сессии и origin.
- Фронт: `RunView`, `RunProgress`, `KpiTile`, `LiveChart` (ECharts, LTTB), `ResourcePanel`, `LogConsole`, `useRunSocket` с переподключением.

## Этап 4. Отчёт

- Парсеры `summary`, `statements`, `agg_log` (слияние файлов потоков), `tx_log` (гистограмма, p50/p95/p99, gzip); фикстуры pgbench 18 против PG 13 и 18.
- Таблицы `runs`, `run_series`, `run_statements`, `run_histogram`; `GET /api/runs/{id}`, `/report`, `/files/{name}`.
- Фронт: `ReportView`, `TimeSeriesChart`, `LatencyBandChart`, `StatementBars`, `LatencyHistogram`, `RunParams`, `RawOutput`.

## Этап 5. История и сравнение

- `run_resources` в отчёте рядом с TPS, `GET /api/runs` с поиском, фильтрами и пагинацией, удаление запусков, `GET /api/runs/compare`, фоновая очистка старше `keep_runs_days`.
- Фронт: `HistoryView`, `RunsTable`, `Sparkline`, `CompareOverlay`, `CompareView`, «Повторить».

## Этап 6. Доводка

- Сверка всех экранов с макетами в обеих темах.
- Playwright e2e в CI: подключение → инициализация → 30-секундный тест → отчёт → сравнение.
- README: установка, конфиг, ограничения.
