from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.audit import actions
from app.core.ui_errors import raise_ui_error
from app.db.database import get_db
from app.security.dependencies import AuthUser, get_current_user, require_roles
from app.security.roles import ROLE_PLATFORM_ADMIN, SETTINGS_VIEW_ROLES, has_any_role
from app.services.audit_service import record_audit
from app.services.data_governance_service import (
    build_data_governance_preview,
    execute_cleanup_synthetic_runtime,
    execute_keep_demo_chain,
    execute_prune_ocr_exports,
)

router = APIRouter(prefix="/settings", tags=["settings"])


class DataGovernanceRunRequest(BaseModel):
    action: str = Field(description="执行动作 / keep_demo_chain | cleanup_synthetic_runtime | prune_ocr_exports")
    keep_latest: int = Field(default=3, ge=1, le=20, description="保留多少版 OCR 导出历史 / Keep latest OCR export versions")
    note: str | None = Field(default=None, description="执行说明 / Optional operator note")


def _serialize_governance_preview(*, keep_latest: int, can_execute: bool) -> dict:
    preview = build_data_governance_preview(keep_latest=keep_latest)
    return {
        "generated_at": datetime.utcnow().isoformat(),
        "keep_latest": keep_latest,
        "can_execute": can_execute,
        "actions": [
            preview["keep_demo_chain"],
            preview["cleanup_synthetic_runtime"],
            preview["prune_ocr_exports"],
        ],
    }


@router.get("/data-governance")
def get_data_governance_preview(
    request: Request,
    keep_latest: int = Query(default=3, ge=1, le=20),
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(*SETTINGS_VIEW_ROLES)),
):
    can_execute = has_any_role(current_user.roles, (ROLE_PLATFORM_ADMIN,))
    payload = _serialize_governance_preview(keep_latest=keep_latest, can_execute=can_execute)
    record_audit(
        db,
        action=actions.DATA_GOVERNANCE_PREVIEW,
        resource_type="data_governance",
        resource_id="preview",
        detail={"keep_latest": keep_latest},
        request=request,
        actor=current_user,
    )
    return payload


@router.post("/data-governance/run")
def run_data_governance_action(
    payload: DataGovernanceRunRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: AuthUser = Depends(require_roles(ROLE_PLATFORM_ADMIN)),
):
    action = str(payload.action or "").strip()
    try:
        if action == "keep_demo_chain":
            result = execute_keep_demo_chain()
        elif action == "cleanup_synthetic_runtime":
            result = execute_cleanup_synthetic_runtime()
        elif action == "prune_ocr_exports":
            result = execute_prune_ocr_exports(keep_latest=payload.keep_latest)
        else:
            raise_ui_error(
                status.HTTP_400_BAD_REQUEST,
                "data_governance_action_invalid",
                "当前数据治理动作不受支持。",
                next_step="请刷新设置页后，重新选择系统提供的治理动作。",
                raw_detail={"action": action},
            )
    except Exception as exc:  # pragma: no cover - runtime safety
        raise_ui_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "data_governance_execute_failed",
            "数据治理执行失败，当前策略没有完整跑完。",
            next_step="请先回到“数据治理”查看预览，再重新执行；若持续失败，请检查脚本输出日志。",
            raw_detail={"action": action, "error": str(exc)},
        )

    detail = {
        "action": action,
        "keep_latest": payload.keep_latest,
        "note": payload.note,
        "result": result,
    }
    record_audit(
        db,
        action=actions.DATA_GOVERNANCE_EXECUTE,
        resource_type="data_governance",
        resource_id=action,
        detail=detail,
        request=request,
        actor=current_user,
    )
    return {
        "executed_at": datetime.utcnow().isoformat(),
        "action": action,
        "result": result,
    }
