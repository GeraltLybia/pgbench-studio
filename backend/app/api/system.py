"""Versions, limits and agent settings the frontend needs."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app import __version__
from app.api.deps import SettingsDep, ViewerDep
from app.core.healthchecks import HealthService
from app.core.limits import agent_cpu_count
from app.schemas import LimitsOut, SystemInfo

router = APIRouter(prefix="/api/system", tags=["system"])

MIN_SERVER_VERSION = 13


@router.get("/info", response_model=SystemInfo)
async def system_info(request: Request, settings: SettingsDep, _user: ViewerDep) -> SystemInfo:
    health: HealthService = request.app.state.health
    if health.pgbench_version is None:
        await health.results()
    return SystemInfo(
        app_version=__version__,
        cpu_count=agent_cpu_count(),
        default_progress_interval_s=settings.pgbench.default_progress_interval_s,
        agent_name=settings.agent.name,
        pgbench_version=health.pgbench_version,
        dev_mode=settings.server.dev_mode,
        cpu_warning_percent=settings.agent.cpu_warning_percent,
        min_server_version=MIN_SERVER_VERSION,
        limits=LimitsOut.model_validate(settings.limits.model_dump()),
    )
