# План работ pgbench studio

Рабочая детализация раздела «План реализации» из [architecture.md](architecture.md). При расхождении прав документ архитектуры. Этапы идут строго по очереди: следующий начинается, когда закрыты все критерии приёмки текущего.

Общий критерий каждого этапа: unit-тесты бэкенда пишутся вместе с кодом, покрытие ≥ 85 % для `backend/app/core` и `backend/app/api`, ≥ 70 % для остального; ruff, mypy --strict, pytest, ESLint, vue-tsc, Vitest — зелёные.

## Принятые трактовки документа

- В разделе «Цель и границы MVP» сказано «без ролей», но раздел «Роли и доступ» и этап 0 требуют ролей `viewer` / `editor` / `admin` — реализуем роли.
- «Изменяющие запросы доступны только роли `editor`» читается как «`editor` и выше»: `admin` может всё, что `editor`.
- Макеты лежат в `docs/design/*.pdf` (перенесены из `design/`), документ архитектуры — `docs/architecture.md`.
- pgbench в образе: в Debian/PGDG он входит не в `postgresql-client-18`, а в серверный пакет `postgresql-18`. Ставится клиентский пакет, из серверного извлекается только бинарник pgbench, сам сервер не устанавливается. (Согласовано 2026-09-27.)
- Ключ шифрования `PGB_STUDIO_SECRET_KEY` обязателен: без него бэкенд не стартует. Фраза этапа 1 «пароль не хранится, если ключа нет» не применяется. Ключ генерируется `studio gen-key` при установке и передаётся через `.env` или секреты инфраструктуры. (Согласовано 2026-09-27.)
- `/readyz` без сессии отдаёт ещё и `pgbench_version` — для подписи «pgbench 18» на экране входа. (Согласовано 2026-09-27.)
- Новый пароль пользователя — не короче 8 символов; при создании пользователя и сбросе пароля временный пароль генерирует сервер и показывает один раз. (Согласовано 2026-09-27.)

## Статус (обновлено 2026-09-27)

### Этап 1 — закрыт (PR #3)

Бэкенд: профили (`profiles`, пароль зашифрован Fernet и не возвращается в API, `has_password`), `POST /api/profiles/test` через psycopg — версия сервера, совместимость с pgbench, время отклика, `max_connections` и свободные, таблицы `pgbench_*`, scale, строки `pgbench_accounts`; классификатор всех 8 кодов ошибок. `POST /api/profiles/{id}/init` — подтверждение именем базы, лимит `max_scale`, подтверждение > 50 ГБ, повторная проверка соединения (при ошибке `422` той же структуры), блокировка при проваленных обязательных health-проверках (`503`), один запуск на агенте (`409`). Раннер `pgbench -i`: только argv, пароль в `PGPASSWORD`, дочерний процесс получает лишь `PATH`, `LC_ALL=C`, `HOME=<каталог запуска>` и `PG*`; разбор прогресса; при рестарте активные запуски помечаются `failed`. `GET /api/runs/{id}` — статус, прогресс, хвост лога.

Фронтенд: экран «Подключение» по макету (форма, выбор профиля, проверка с успехом и ошибкой, инициализация с подтверждением вводом имени базы и прогрессом), карточка «Текущее подключение» в меню, guard «нет успешной проверки → `/connect`», автопроверка сохранённого профиля при открытии, результат проверки привязан к хешу параметров.

Критерии этапа 1:

| Критерий | Результат |
| --- | --- |
| CRUD профилей, пароль зашифрован | unit-тесты: в SQLite не открытый текст, расшифровывается ключом, в ответах API пароля нет; обновление сохраняет, заменяет и удаляет пароль |
| «Проверить соединение»: версия, совместимость, `max_connections`, таблицы, scale | в браузере на `pg18` из compose: PostgreSQL 18.x, pgbench 18.6 · совместим, 100 (свободно 96), найдены · scale; через API для `pg13` — 13.23 |
| без проверки на «Нагрузку» нельзя; коды ошибок с причиной и подсказкой | кнопка и пункт меню неактивны, прямой `/load` возвращает на `/connect` (браузер + Vitest guard-ов); все 8 кодов — unit-тесты классификатора и API, интеграционные тесты на живом сервере для каждого кода |
| pgbench 18 инициализирует и проводит тест на PG 13 и 18 | интеграционные тесты (Testcontainers): `pgbench -i -s 2` и `pgbench -c 2 -j 2 -T 3` на `postgres:13` и `postgres:18`; job `integration` в CI |
| `pgbench -i` только после ввода имени базы, прогресс в интерфейсе | диалог подтверждения (кнопка активна только при точном совпадении, бэкенд проверяет `confirm_dbname`), прогресс «Генерация данных 74.5 % · осталось 2 с» в браузере на scale 200 |

Решения этапа 1, которых нет в документе (согласованы 2026-09-27):

- Прогресс `pgbench -i` фронт получает опросом `GET /api/runs/{id}` раз в секунду: WebSocket запуска появится на этапе 3.
- Имя нового профиля формируется автоматически — «хост · база» (как «stage-db · bench» на макете): поля имени на макете нет.
- SSL mode — четыре значения с макета: `disable`, `prefer`, `require`, `verify-full`.
- Для инициализации больше 50 ГБ нужен флажок подтверждения; бэкенд без него отвечает `422`.
- Наблюдатель (`viewer`) не может проверять соединение, поэтому guard «нужна проверка» для него действует только на «Нагрузку»; экраны «Выполнение» и «Отчёт» ему доступны (наблюдение за тестом разрешено ролью).
- Число свободных соединений = `max_connections` − `superuser_reserved_connections` − `reserved_connections` (PG 16+) − клиентские сессии в `pg_stat_activity`.

### Этап 0 — закрыт

Этап 0 реализован и принят (PR #1), CI зелёный (PR #2). Остаётся проверка на стенде с реальным балансировщиком (см. ниже).

Бэкенд (`backend/`): конфиг с понятной ошибкой старта, SQLite + Alembic, вход с блокировкой по логину и реальному IP, роли, обязательная смена временного пароля, управление пользователями, отказ изменяющих запросов не по HTTPS, `/healthz`, `/readyz`, `/api/system/health`, `/api/system/info`, CLI `studio`, образ с pgbench 18. 120 тестов, покрытие `app/api` 98.9 %, `app/core` 100 %, прочее 99.4 %.

Фронтенд (`frontend/`): оболочка с меню, индикатором состояния (список проверок по клику), меню пользователя и переключателем темы; экраны входа (по макету, с числом оставшихся попыток), смены пароля, «Пользователи» для `admin`, пустые экраны остальных разделов; guard-ы входа, роли и временного пароля; типы API из OpenAPI. ESLint, vue-tsc чистые, Vitest — 58 тестов.

Инфраструктура: `frontend/Dockerfile` + nginx (прокси `/api` и WS, `/healthz` через бэкенд, доверие `X-Forwarded-*` только от `TRUSTED_PROXIES`), `docker-compose.yml` (backend, frontend, pg13, pg18 — все `healthy`), CI в `.github/workflows/ci.yml`.

Критерии этапа 0:

| Критерий | Результат |
| --- | --- |
| `docker compose up` поднимает агент и PG 13/18 | да, `docker compose ps` — 4 × `healthy` |
| healthcheck, `/healthz`, `/readyz`, индикатор в меню | да, через `localhost:8080`; индикатор и список проверок в браузере |
| вход `editor`/`viewer`, матрица прав, `403` для `viewer` | unit-тесты матрицы по всем эндпоинтам; через nginx `viewer` получает `403` на `POST /api/users` |
| админ управляет пользователями, временный пароль, последний `admin` | unit-тесты + проверено в интерфейсе и через nginx |
| балансировщик | эмуляция на compose с `dev_mode: false`: вход только с `X-Forwarded-Proto: https` от доверенного адреса, cookie `Secure; HttpOnly; SameSite=strict`, реальный IP клиента в логах и в блокировке; подделанные заголовки от недоверенного адреса → `403 https_required`. Таймаут WS в nginx — `max_duration_s + 60 с`. **Не проверено**: реальный балансировщик и WebSocket на тесте 1 ч — WS появится на этапе 3, балансировщик на стороне инфраструктуры |
| `localhost:8080`: меню, пустые экраны, тема | да, обе темы |
| ошибка в `config.yaml` останавливает старт | да: контейнер `backend` не стартует, в логе `server.port: … (значение: 'abc')`, код выхода 2 |
| CI: ruff, mypy, pytest + пороги, ESLint, vue-tsc, Vitest | да, GitHub Actions: `backend`, `frontend` (включая актуальность типов API), `images` — зелёные |

Отложено: проверку «Зависшие запуски» из раздела «Health check» добавим в этапе 3 вместе с таблицей `runs`.

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

## Бэклог (вне этапов документа)

Задачи, которых нет в документе архитектуры. Берутся в работу только по отдельному решению, после согласования деталей.

- **Смена ключа шифрования профилей.** Сейчас при потере или замене `PGB_STUDIO_SECRET_KEY` сохранённые пароли профилей не расшифровать — их вводят заново. Нужна процедура смены ключа без потери паролей. Набросок: CLI `studio keys rotate` в контейнере бэкенда при остановленном агенте. Старый ключ берётся из текущей переменной, новый — из отдельной (например `PGB_STUDIO_SECRET_KEY_NEW`); все `profiles.password_enc` перешифровываются в одной транзакции (`cryptography.fernet.MultiFernet.rotate`). Затем оператор меняет ключ в `.env` и перезапускает агента. Health check сообщает о паролях, которые не расшифровываются текущим ключом. Тесты: успешная ротация, неверный старый ключ, откат при ошибке посередине. Согласовать: нужен ли период, когда принимаются оба ключа, и кто имеет право запускать ротацию.

