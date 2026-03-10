from __future__ import annotations

from typing import Any

from fastapi import HTTPException


def build_ui_error(
    code: str,
    message: str,
    *,
    next_step: str | None = None,
    hint: str | None = None,
    raw_detail: Any | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "code": code,
        "message": message,
    }
    if next_step:
        payload["next_step"] = next_step
    if hint:
        payload["hint"] = hint
    if raw_detail is not None:
        payload["raw_detail"] = raw_detail
    return payload


def raise_ui_error(
    status_code: int,
    code: str,
    message: str,
    *,
    next_step: str | None = None,
    hint: str | None = None,
    raw_detail: Any | None = None,
) -> None:
    raise HTTPException(
        status_code=status_code,
        detail=build_ui_error(
            code,
            message,
            next_step=next_step,
            hint=hint,
            raw_detail=raw_detail,
        ),
    )
