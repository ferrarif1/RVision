from __future__ import annotations

from typing import Any

from app.core.constants import MODEL_STATUS_APPROVED, MODEL_STATUS_RELEASED
from app.db.models import DataAsset, ModelRecord, TrainingJob

CANDIDATE_SOURCE_TYPES = {"finetuned_candidate", "delivery_candidate"}


def _safe_number(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if numeric == numeric else None


def _clean_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def build_platform_meta(model: ModelRecord) -> dict[str, Any]:
    manifest = model.manifest if isinstance(model.manifest, dict) else {}
    platform_meta = manifest.get("platform_meta")
    return dict(platform_meta) if isinstance(platform_meta, dict) else {}


def merge_platform_meta(model: ModelRecord, updates: dict[str, Any]) -> dict[str, Any]:
    manifest = dict(model.manifest or {})
    platform_meta = build_platform_meta(model)
    for key, value in updates.items():
        if value is None:
            platform_meta.pop(key, None)
        else:
            platform_meta[key] = value
    manifest["platform_meta"] = platform_meta
    model.manifest = manifest
    return platform_meta


def _append_check(checks: list[dict[str, str]], *, code: str, label: str, status: str, reason: str) -> None:
    checks.append({"code": code, "label": label, "status": status, "reason": reason})


def _validation_assets(model_meta: dict[str, Any], training_job: TrainingJob | None, override_asset_ids: list[str] | None) -> list[str]:
    if override_asset_ids:
        return [str(item).strip() for item in override_asset_ids if str(item).strip()]
    if training_job and isinstance(training_job.validation_asset_ids, list) and training_job.validation_asset_ids:
        return [str(item).strip() for item in training_job.validation_asset_ids if str(item).strip()]
    stored = model_meta.get("validation_asset_ids")
    if isinstance(stored, list):
        return [str(item).strip() for item in stored if str(item).strip()]
    return []


def _dataset_provenance_summary(db, *, training_job: TrainingJob | None, validation_asset_ids: list[str]) -> dict[str, Any]:
    asset_ids: list[str] = []
    if training_job and isinstance(training_job.asset_ids, list):
        asset_ids.extend(str(item).strip() for item in training_job.asset_ids if str(item).strip())
    asset_ids.extend(validation_asset_ids)
    asset_ids = [item for item in dict.fromkeys(asset_ids) if item]
    if not asset_ids:
        return {"asset_count": 0, "proxy_seeded_rows": 0, "reviewer_counts": {}}
    assets = db.query(DataAsset).filter(DataAsset.id.in_(asset_ids)).all()
    proxy_seeded_rows = 0
    reviewer_counts: dict[str, int] = {}
    for asset in assets:
        meta = asset.meta if isinstance(asset.meta, dict) else {}
        proxy_seeded_rows += int(meta.get("proxy_seeded_rows") or 0)
        raw_counts = meta.get("reviewer_counts")
        if isinstance(raw_counts, dict):
            for key, value in raw_counts.items():
                reviewer = str(key or "").strip() or "unknown"
                reviewer_counts[reviewer] = reviewer_counts.get(reviewer, 0) + int(value or 0)
    return {
        "asset_count": len(assets),
        "proxy_seeded_rows": proxy_seeded_rows,
        "reviewer_counts": reviewer_counts,
    }


def build_model_validation_report(
    db,
    model: ModelRecord,
    *,
    override_validation_asset_ids: list[str] | None = None,
) -> dict[str, Any]:
    platform_meta = build_platform_meta(model)
    training_job_id = _clean_text(platform_meta.get("training_job_id"))
    training_job = db.query(TrainingJob).filter(TrainingJob.id == training_job_id).first() if training_job_id else None
    output_summary = training_job.output_summary if training_job and isinstance(training_job.output_summary, dict) else {}
    source_type = str(platform_meta.get("model_source_type") or "").strip() or "delivery_candidate"
    is_candidate = source_type in CANDIDATE_SOURCE_TYPES or bool(training_job_id)

    val_score = _safe_number(output_summary.get("val_score") or output_summary.get("validation_score"))
    val_accuracy = _safe_number(output_summary.get("val_accuracy") or output_summary.get("validation_accuracy"))
    val_loss = _safe_number(output_summary.get("val_loss") or output_summary.get("validation_loss"))
    history = output_summary.get("history")
    history_count = int(output_summary.get("history_count") or (len(history) if isinstance(history, list) else 0) or 0)
    best_checkpoint = output_summary.get("best_checkpoint") if isinstance(output_summary.get("best_checkpoint"), dict) else None
    validation_asset_ids = _validation_assets(platform_meta, training_job, override_validation_asset_ids)
    provenance = _dataset_provenance_summary(db, training_job=training_job, validation_asset_ids=validation_asset_ids)
    training_summary = _clean_text(platform_meta.get("training_summary"))
    dataset_label = _clean_text(platform_meta.get("dataset_label"))

    checks: list[dict[str, str]] = []
    runtime_contract_ok = bool(model.runtime and model.plugin_name and isinstance(model.inputs, dict) and model.inputs and isinstance(model.outputs, dict) and model.outputs)
    if runtime_contract_ok:
        _append_check(checks, code="runtime_contract", label="运行时契约", status="ok", reason="已具备 runtime / plugin / inputs / outputs")
    else:
        _append_check(checks, code="runtime_contract", label="运行时契约", status="blocked", reason="缺少 runtime、plugin 或输入输出协议，不能进入审批")

    _append_check(checks, code="package_integrity", label="模型包验签", status="ok", reason="模型包已通过签名校验并成功入库")

    if training_job_id and not training_job:
        _append_check(checks, code="training_context", label="训练上下文", status="blocked", reason="候选模型引用的训练作业不存在，无法核对数据来源")
    elif training_job:
        _append_check(checks, code="training_context", label="训练上下文", status="ok", reason=f"已关联训练作业 {training_job.job_code}")
    elif is_candidate:
        _append_check(checks, code="training_context", label="训练上下文", status="warning", reason="候选模型未绑定训练作业，只能依赖人工补充说明")

    has_validation_metrics = any(metric is not None for metric in (val_score, val_accuracy, val_loss))
    if validation_asset_ids:
        _append_check(checks, code="validation_assets", label="验证数据", status="ok", reason=f"已关联 {len(validation_asset_ids)} 个验证资产")
    elif is_candidate:
        _append_check(checks, code="validation_assets", label="验证数据", status="blocked", reason="候选模型未绑定验证资产，不能进入审批")
    else:
        _append_check(checks, code="validation_assets", label="验证数据", status="warning", reason="尚未记录验证资产")

    if has_validation_metrics:
        _append_check(checks, code="validation_metrics", label="验证指标", status="ok", reason="已具备至少一项验证指标")
    elif is_candidate:
        _append_check(checks, code="validation_metrics", label="验证指标", status="blocked", reason="候选模型缺少验证指标，不能进入审批")
    else:
        _append_check(checks, code="validation_metrics", label="验证指标", status="warning", reason="尚未记录验证指标")

    if best_checkpoint:
        _append_check(checks, code="best_checkpoint", label="最优检查点", status="ok", reason="训练产物已记录 best checkpoint")
    elif is_candidate:
        _append_check(checks, code="best_checkpoint", label="最优检查点", status="warning", reason="未记录 best checkpoint，建议补充最优轮次信息")

    if history_count > 0:
        _append_check(checks, code="training_history", label="训练历史", status="ok", reason=f"已回收 {history_count} 个 epoch 历史点")
    elif is_candidate:
        _append_check(checks, code="training_history", label="训练历史", status="warning", reason="未回收 epoch 级历史指标")

    if model.gpu_mem_mb is not None and model.latency_ms is not None:
        _append_check(checks, code="runtime_budget", label="运行预算", status="ok", reason="已记录显存与时延预算")
    else:
        _append_check(checks, code="runtime_budget", label="运行预算", status="warning", reason="缺少 gpu_mem_mb 或 latency_ms，发布前风险不可见")

    if dataset_label or training_summary:
        _append_check(checks, code="data_lineage", label="数据来源摘要", status="ok", reason="已记录数据标签或训练摘要")
    elif is_candidate:
        _append_check(checks, code="data_lineage", label="数据来源摘要", status="warning", reason="建议补充 dataset_label 或 training_summary")

    if provenance.get("proxy_seeded_rows"):
        _append_check(
            checks,
            code="proxy_truth_risk",
            label="代理真值风险",
            status="warning",
            reason=f"训练/验证数据中包含 {provenance.get('proxy_seeded_rows')} 条代理回灌文本，建议继续补真实标记真值后再做审批结论。",
        )

    blocker_count = sum(1 for item in checks if item["status"] == "blocked")
    warning_count = sum(1 for item in checks if item["status"] == "warning")
    ok_count = sum(1 for item in checks if item["status"] == "ok")
    decision = "blocked" if blocker_count else ("warning" if warning_count else "passed")
    summary = (
        f"自动验证发现 {blocker_count} 个阻断项、{warning_count} 个提醒项。"
        if blocker_count or warning_count
        else "自动验证通过，当前候选模型具备进入审批的基础证据。"
    )
    return {
        "decision": decision,
        "can_approve": blocker_count == 0,
        "validation_result": "failed" if blocker_count else "passed",
        "summary": summary,
        "source_type": source_type,
        "training_job": {
            "id": training_job.id,
            "job_code": training_job.job_code,
            "status": training_job.status,
        } if training_job else None,
        "validation_asset_ids": validation_asset_ids,
        "metrics": {
            "val_score": val_score,
            "val_accuracy": val_accuracy,
            "val_loss": val_loss,
            "history_count": history_count,
            "history": history if isinstance(history, list) else [],
            "best_checkpoint": best_checkpoint,
            "latency_ms": model.latency_ms,
            "gpu_mem_mb": model.gpu_mem_mb,
        },
        "data_provenance": provenance,
        "counts": {
            "blocker_count": blocker_count,
            "warning_count": warning_count,
            "ok_count": ok_count,
        },
        "checks": checks,
    }


def build_model_release_risk_summary(
    model: ModelRecord,
    validation_report: dict[str, Any],
    *,
    target_devices: list[str],
    target_buyers: list[str],
    delivery_mode: str,
    authorization_mode: str,
    runtime_encryption: bool,
    api_access_key_label: str | None,
    local_key_label: str | None,
) -> dict[str, Any]:
    checks: list[dict[str, str]] = []

    if model.status in {MODEL_STATUS_APPROVED, MODEL_STATUS_RELEASED}:
        _append_check(checks, code="model_status", label="审批状态", status="ok", reason=f"模型当前状态为 {model.status}")
    else:
        _append_check(checks, code="model_status", label="审批状态", status="blocked", reason="模型尚未审批通过，不能进入发布")

    if validation_report.get("can_approve"):
        _append_check(checks, code="validation_gate", label="验证门禁", status="ok", reason=validation_report.get("summary") or "自动验证通过")
    else:
        _append_check(checks, code="validation_gate", label="验证门禁", status="blocked", reason=validation_report.get("summary") or "自动验证未通过")

    if delivery_mode == "api" and authorization_mode == "device_key":
        _append_check(checks, code="delivery_auth", label="交付与授权组合", status="blocked", reason="API 交付不能只使用 device_key 授权")
    elif delivery_mode == "local_key" and authorization_mode == "api_token":
        _append_check(checks, code="delivery_auth", label="交付与授权组合", status="blocked", reason="本地加密交付不能只使用 api_token 授权")
    elif delivery_mode == "hybrid" and authorization_mode != "hybrid":
        _append_check(checks, code="delivery_auth", label="交付与授权组合", status="blocked", reason="hybrid 交付必须搭配 hybrid 授权")
    else:
        _append_check(checks, code="delivery_auth", label="交付与授权组合", status="ok", reason="交付模式与授权模式匹配")

    if delivery_mode in {"local_key", "hybrid"} and not runtime_encryption:
        _append_check(checks, code="runtime_encryption", label="运行时解密要求", status="blocked", reason="本地交付必须开启 runtime_encryption")
    else:
        _append_check(checks, code="runtime_encryption", label="运行时解密要求", status="ok", reason="运行时解密策略满足当前交付模式")

    if target_devices:
        _append_check(checks, code="device_scope", label="设备授权范围", status="ok", reason=f"已限定 {len(target_devices)} 台设备")
    else:
        _append_check(checks, code="device_scope", label="设备授权范围", status="warning", reason="未限定设备范围，发布后所有设备都可能可见")

    if target_buyers:
        _append_check(checks, code="buyer_scope", label="买家授权范围", status="ok", reason=f"已限定 {len(target_buyers)} 个买家租户")
    else:
        _append_check(checks, code="buyer_scope", label="买家授权范围", status="warning", reason="未限定买家范围，发布后所有买家都可能可见")

    if delivery_mode in {"api", "hybrid"} and not _clean_text(api_access_key_label):
        _append_check(checks, code="api_access_key_label", label="API 密钥标签", status="warning", reason="建议显式填写 API 访问键标签")
    if delivery_mode in {"local_key", "hybrid"} and not _clean_text(local_key_label):
        _append_check(checks, code="local_key_label", label="本地密钥标签", status="warning", reason="建议显式填写本地密钥标签")

    if model.gpu_mem_mb is None or model.latency_ms is None:
        _append_check(checks, code="runtime_budget", label="容量评估", status="warning", reason="缺少显存或时延预算，容量评估仍不完整")
    else:
        _append_check(checks, code="runtime_budget", label="容量评估", status="ok", reason="已记录显存和时延预算")

    blocker_count = sum(1 for item in checks if item["status"] == "blocked")
    warning_count = sum(1 for item in checks if item["status"] == "warning")
    ok_count = sum(1 for item in checks if item["status"] == "ok")
    decision = "blocked" if blocker_count else ("warning" if warning_count else "passed")
    summary = (
        f"发布前评估发现 {blocker_count} 个阻断项、{warning_count} 个提醒项。"
        if blocker_count or warning_count
        else "发布前评估通过，当前授权范围和交付策略可直接发布。"
    )
    return {
        "decision": decision,
        "can_release": blocker_count == 0,
        "summary": summary,
        "counts": {
            "blocker_count": blocker_count,
            "warning_count": warning_count,
            "ok_count": ok_count,
        },
        "scope": {
            "target_device_count": len(target_devices),
            "target_buyer_count": len(target_buyers),
            "open_device_scope": not bool(target_devices),
            "open_buyer_scope": not bool(target_buyers),
        },
        "config": {
            "delivery_mode": delivery_mode,
            "authorization_mode": authorization_mode,
            "runtime_encryption": bool(runtime_encryption),
            "api_access_key_label": _clean_text(api_access_key_label),
            "local_key_label": _clean_text(local_key_label),
        },
        "checks": checks,
    }
