"""Script library, script validation and pgbench builtin scripts."""

from __future__ import annotations

import asyncio
import logging
import re

from fastapi import APIRouter, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DbDep, EditorDep, SettingsDep, ViewerDep, client_ip
from app.api.errors import api_error
from app.core.validator import validate_script
from app.schemas import (
    BuiltinOut,
    DiagnosticOut,
    ErrorResponse,
    ScriptIn,
    ScriptOut,
    ValidateRequest,
    ValidateResponse,
)
from app.storage.models import Script, utcnow

log = logging.getLogger(__name__)

router = APIRouter(tags=["scripts"])

BUILTIN_NAMES = ("tpcb-like", "simple-update", "select-only")
_TITLE_RE = re.compile(r"<builtin: (.*)>")

_ERRORS: dict[int | str, dict[str, object]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
}


async def _get_or_404(db: DbDep, script_id: int) -> Script:
    script = await db.get(Script, script_id)
    if script is None:
        raise api_error(404, "script_not_found", "Сценарий не найден")
    return script


@router.get("/api/scripts", response_model=list[ScriptOut], responses=_ERRORS)
async def list_scripts(db: DbDep, _user: ViewerDep) -> list[Script]:
    result = await db.execute(select(Script).order_by(Script.name))
    return list(result.scalars())


@router.post(
    "/api/scripts",
    response_model=ScriptOut,
    status_code=201,
    responses={**_ERRORS, 409: {"model": ErrorResponse}},
)
async def create_script(body: ScriptIn, request: Request, db: DbDep, user: EditorDep) -> Script:
    script = Script(name=body.name, body=body.body)
    db.add(script)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise api_error(409, "script_exists", "Сценарий с таким именем уже есть") from exc
    log.info(
        "script created",
        extra={"ip": client_ip(request), "username": user.username, "script": script.name},
    )
    return script


@router.put(
    "/api/scripts/{script_id}",
    response_model=ScriptOut,
    responses={**_ERRORS, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def update_script(
    script_id: int, body: ScriptIn, request: Request, db: DbDep, user: EditorDep
) -> Script:
    script = await _get_or_404(db, script_id)
    script.name = body.name
    script.body = body.body
    script.updated_at = utcnow()
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise api_error(409, "script_exists", "Сценарий с таким именем уже есть") from exc
    log.info(
        "script updated",
        extra={"ip": client_ip(request), "username": user.username, "script": script.name},
    )
    return script


@router.delete(
    "/api/scripts/{script_id}",
    status_code=204,
    responses={**_ERRORS, 404: {"model": ErrorResponse}},
)
async def delete_script(script_id: int, request: Request, db: DbDep, user: EditorDep) -> Response:
    script = await _get_or_404(db, script_id)
    await db.delete(script)
    await db.commit()
    log.info(
        "script deleted",
        extra={"ip": client_ip(request), "username": user.username, "script": script.name},
    )
    return Response(status_code=204)


@router.post("/api/scripts/validate", response_model=ValidateResponse, responses=_ERRORS)
async def validate(body: ValidateRequest, _user: ViewerDep) -> ValidateResponse:
    # Parsing is CPU-bound but fast; a thread keeps the loop free for large scripts.
    result = await asyncio.to_thread(
        validate_script, body.body, body.server_major, frozenset(body.variables)
    )
    return ValidateResponse(
        diagnostics=[
            DiagnosticOut(
                line=d.line,
                col=d.col,
                end_col=d.end_col,
                severity=d.severity,
                message=d.message,
                rule=d.rule,
            )
            for d in result.diagnostics
        ],
        variables_used=result.variables_used,
        variables_defined=result.variables_defined,
        has_errors=result.has_errors,
    )


async def load_builtins(binary: str) -> list[BuiltinOut]:
    """Texts of the builtin scripts exactly as the agent's pgbench runs them."""
    builtins: list[BuiltinOut] = []
    for name in BUILTIN_NAMES:
        proc = await asyncio.create_subprocess_exec(
            binary,
            f"--show-script={name}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), 10)
        text = out.decode(errors="replace")
        first, _, body = text.partition("\n")
        match = _TITLE_RE.search(first)
        builtins.append(
            BuiltinOut(name=name, title=match.group(1) if match else name, body=body.strip() + "\n")
        )
    return builtins


@router.get(
    "/api/builtins",
    response_model=list[BuiltinOut],
    responses={**_ERRORS, 503: {"model": ErrorResponse}},
)
async def builtins(request: Request, settings: SettingsDep, _user: ViewerDep) -> list[BuiltinOut]:
    cached: list[BuiltinOut] | None = getattr(request.app.state, "builtins", None)
    if cached is None:
        try:
            cached = await load_builtins(settings.pgbench.binary)
        except (OSError, TimeoutError) as exc:
            raise api_error(
                503, "pgbench_unavailable", "pgbench недоступен: не удалось получить сценарии"
            ) from exc
        request.app.state.builtins = cached
    return cached
