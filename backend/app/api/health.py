"""Liveness, readiness and the detailed health report."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.api.deps import ViewerDep
from app.core.healthchecks import HealthService, overall_status
from app.schemas import HealthCheckOut, Liveness, Readiness, SystemHealth

router = APIRouter(tags=["health"])


def _service(request: Request) -> HealthService:
    service: HealthService = request.app.state.health
    return service


@router.get("/healthz", response_model=Liveness)
async def healthz() -> Liveness:
    return Liveness(status="ok")


@router.get("/readyz", response_model=Readiness, responses={503: {"model": Readiness}})
async def readyz(request: Request) -> JSONResponse:
    service = _service(request)
    _, results = await service.results()
    failed = [r.name for r in results if r.required and r.status == "fail"]
    body = Readiness(
        status="fail" if failed else "ok", failed=failed, pgbench_version=service.pgbench_version
    )
    return JSONResponse(body.model_dump(), status_code=503 if failed else 200)


@router.get("/api/system/health", response_model=SystemHealth, tags=["system"])
async def system_health(request: Request, _user: ViewerDep) -> SystemHealth:
    checked_at, results = await _service(request).results()
    return SystemHealth(
        status=overall_status(results),
        checked_at=checked_at,
        checks=[
            HealthCheckOut(
                name=r.name,
                title=r.title,
                required=r.required,
                status=r.status,
                value=r.value,
                threshold=r.threshold,
                message=r.message,
            )
            for r in results
        ],
    )
