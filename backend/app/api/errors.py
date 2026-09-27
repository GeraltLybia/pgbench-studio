"""Uniform API errors: {"detail": {"code": ..., "message": ..., ...}}."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException


def api_error(
    status_code: int, code: str, message: str, headers: dict[str, str] | None = None, **extra: Any
) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, **extra},
        headers=headers,
    )
