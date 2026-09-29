"""Application factory: routers, middleware and startup."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app import __version__
from app.api import auth, health, profiles, runs, scripts, system, users, ws
from app.config import Settings, load_settings
from app.core.connection import check_connection
from app.core.healthchecks import HealthService
from app.core.retention import purge_loop
from app.core.runner import AgentOptions, RunManager
from app.security.login_guard import IpLoginGuard
from app.security.sessions import purge_expired
from app.storage import repo
from app.storage.crypto import SecretBox
from app.storage.db import create_engine_for, head_revision, make_sessionmaker, run_migrations

log = logging.getLogger(__name__)

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


async def startup(app: FastAPI, settings: Settings) -> None:
    key = settings.secret_key()  # refuses to start without a valid key
    storage = settings.storage
    await asyncio.to_thread(run_migrations, storage.sqlite_path)
    storage.runs_dir.mkdir(parents=True, exist_ok=True)

    engine = create_engine_for(storage.sqlite_path)
    sessionmaker = make_sessionmaker(engine)
    async with sessionmaker() as db:
        await repo.bootstrap_admin(
            db,
            os.environ.get(settings.auth.admin_user_env),
            os.environ.get(settings.auth.admin_password_env),
        )
        await purge_expired(db)
        await db.commit()

    app.state.engine = engine
    app.state.sessionmaker = sessionmaker
    app.state.login_guard = IpLoginGuard(
        settings.auth.max_failed_logins, timedelta(minutes=settings.auth.lockout_min)
    )
    app.state.health = HealthService(
        settings,
        app.state.config_file,
        head_revision(storage.sqlite_path),
        stuck_runs=lambda: app.state.runs.stuck_runs(),
    )
    app.state.secret_box = SecretBox(key)
    app.state.connection_checker = check_connection
    app.state.runs = RunManager(
        sessionmaker,
        storage.runs_dir,
        settings.pgbench.max_parallel_runs,
        settings.pgbench.binary,
        agent=AgentOptions(
            name=settings.agent.name,
            sample_interval_s=settings.agent.sample_interval_s,
            cpu_warning_percent=settings.agent.cpu_warning_percent,
        ),
    )
    await app.state.runs.recover()
    app.state.purge = asyncio.create_task(
        purge_loop(
            sessionmaker,
            storage.runs_dir,
            storage.keep_runs_days,
            lambda: app.state.runs.active_ids,
        )
    )


def create_app(settings: Settings | None = None, config_file: Path | None = None) -> FastAPI:
    settings = settings or load_settings(config_file)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await startup(app, settings)
        log.info("backend started", extra={"version": __version__, "agent": settings.agent.name})
        yield
        # Wait for the purge to stop before the engine goes: a pass cancelled mid-query
        # would otherwise leave an aiosqlite connection behind while the engine is disposed.
        app.state.purge.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await app.state.purge
        await app.state.runs.shutdown()
        await app.state.engine.dispose()

    app = FastAPI(
        title="pgbench studio",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs" if settings.server.dev_mode else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.server.dev_mode else None,
    )
    app.state.settings = settings
    app.state.config_file = config_file

    @app.middleware("http")
    async def require_https_for_mutations(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # The load balancer terminates TLS; uvicorn sets the scheme from X-Forwarded-Proto
        # only for trusted proxies, so a request bypassing it arrives as plain http.
        if (
            not settings.server.dev_mode
            and request.method not in SAFE_METHODS
            and request.url.scheme != "https"
        ):
            return JSONResponse(
                {
                    "detail": {
                        "code": "https_required",
                        "message": "Изменяющие запросы принимаются только по HTTPS",
                    }
                },
                status_code=403,
            )
        return await call_next(request)

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(system.router)
    app.include_router(profiles.router)
    app.include_router(ws.router)
    app.include_router(runs.router)
    app.include_router(scripts.router)
    return app
