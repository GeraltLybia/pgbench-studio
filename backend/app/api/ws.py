"""WebSocket of a run: `snapshot` first, then log / progress / resources / warning / status."""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections import deque
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.config import Settings
from app.core.events import SNAPSHOT_LOG_LINES, Message, RunEvents
from app.core.runner import RunManager
from app.security.sessions import SESSION_COOKIE, resolve_session
from app.storage.models import Run, utcnow

log = logging.getLogger(__name__)

router = APIRouter()

# Application close codes: 4000 + the HTTP status they stand for.
CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_NOT_FOUND = 4404


def same_origin(websocket: WebSocket) -> bool:
    """Browsers always send Origin on WebSocket; only the app's own origin is accepted.

    Behind nginx the public host is X-Forwarded-Host: nginx sets it itself (from the trusted
    balancer or from the request's Host), so a client cannot forge it. Without a proxy
    (dev server) the Host header is compared.
    """
    origin = websocket.headers.get("origin")
    host = websocket.headers.get("x-forwarded-host") or websocket.headers.get("host")
    return bool(origin and host and urlsplit(origin).netloc == host)


def _file_tail(path: Path, stream: str) -> list[Message]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", errors="replace") as fh:
        lines = deque((line.rstrip("\n") for line in fh), maxlen=SNAPSHOT_LOG_LINES)
    return [{"type": "log", "seq": 0, "ts": None, "stream": stream, "line": x} for x in lines if x]


def stored_snapshot(run: Run, settings: Settings) -> Message:
    """Snapshot of a run whose events are no longer in memory (finished long ago, restart)."""
    config: dict[str, Any] = json.loads(run.config_json)
    run_config: dict[str, Any] = config.get("run_config", {})
    run_dir = settings.storage.runs_dir / str(run.id)
    return {
        "type": "snapshot",
        "seq": 0,
        "ts": utcnow().isoformat(),
        "run_id": run.id,
        "status": {
            "type": "status",
            "status": run.status,
            "exit_code": None,
            "error": run.error,
            "stopped_by": run.stopped_by,
        },
        "config": {
            **run_config,
            "kind": run.kind,
            "argv": json.loads(run.argv_json),
            "run_id": run.id,
            "profile_name": config.get("profile_name"),
            "started_by": run.started_by,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "server_version": run.server_version,
            "pgbench_version": run.pgbench_version,
            "agent_name": settings.agent.name,
            "scenarios": [
                {"kind": s.get("kind"), "name": s.get("name"), "weight": s.get("weight")}
                for s in run_config.get("scenarios", [])
            ],
        },
        "log": _file_tail(run_dir / "stdout.log", "stdout")
        + _file_tail(run_dir / "stderr.log", "stderr"),
        "progress": [],
        "resources": [],
        "warnings": [],
    }


async def _authorize(websocket: WebSocket, run_id: int) -> Run | int:
    """The run, or the close code to reject the connection with."""
    if not same_origin(websocket):
        return CLOSE_FORBIDDEN
    token = websocket.cookies.get(SESSION_COOKIE)
    async with websocket.app.state.sessionmaker() as db:
        session = await resolve_session(db, token) if token else None
        await db.commit()
        if session is None or session.user.disabled:
            return CLOSE_UNAUTHORIZED
        if session.user.must_change_password:
            return CLOSE_FORBIDDEN
        run: Run | None = await db.get(Run, run_id)
        return run if run is not None else CLOSE_NOT_FOUND


@router.websocket("/api/runs/{run_id}/ws")
async def run_socket(websocket: WebSocket, run_id: int) -> None:
    # Every role may watch a run (viewer and up); mutations stay on REST with role checks.
    decision = await _authorize(websocket, run_id)
    if isinstance(decision, int):
        await websocket.close(code=decision)
        return
    await websocket.accept()

    runs: RunManager = websocket.app.state.runs
    settings: Settings = websocket.app.state.settings
    events: RunEvents | None = runs.hub.get(run_id)
    send_lock = asyncio.Lock()

    async def send(message: Message) -> None:
        async with send_lock:
            await websocket.send_json(message)

    if events is None or events.finished:
        # Nothing more will happen: the snapshot is the whole story; close normally.
        await send(stored_snapshot(decision, settings) if events is None else events.snapshot())
        await websocket.close(code=1000)
        return

    snapshot, queue = events.subscribe()
    await send(snapshot)

    async def forward() -> None:
        while (message := await queue.get()) is not None:
            await send(message)

    async def receive() -> None:
        # The client pings every 30 s so idle proxies keep the connection open.
        while True:
            text = await websocket.receive_text()
            with contextlib.suppress(ValueError, TypeError):
                if json.loads(text).get("type") == "ping":
                    await send({"type": "pong", "ts": utcnow().isoformat()})

    forwarder = asyncio.create_task(forward())
    receiver = asyncio.create_task(receive())
    try:
        done, _ = await asyncio.wait({forwarder, receiver}, return_when=asyncio.FIRST_COMPLETED)
        if forwarder in done and not forwarder.exception():
            # The run finished and the bus closed: end the stream normally.
            with contextlib.suppress(Exception):
                await websocket.close(code=1000)
    except WebSocketDisconnect:  # pragma: no cover - raised inside the tasks
        pass
    finally:
        for task in (forwarder, receiver):
            task.cancel()
        for task in (forwarder, receiver):
            with contextlib.suppress(asyncio.CancelledError, WebSocketDisconnect, RuntimeError):
                await task
        events.unsubscribe(queue)
