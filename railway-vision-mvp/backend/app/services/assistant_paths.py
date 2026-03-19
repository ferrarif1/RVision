from __future__ import annotations


def build_workflow_path(action_id: str, expert_path: str) -> str:
    normalized_action = str(action_id or "").strip()
    normalized_path = str(expert_path or "").strip()
    if normalized_action == "upload_or_select_assets" or normalized_path == "assets":
        return "ai/workflow/upload"
    if normalized_action == "prepare_training_data" or normalized_path.startswith("training"):
        return "ai/workflow/train"
    if normalized_action in {"open_approval_workbench", "open_release_workbench"} or normalized_path in {"models", "pipelines"}:
        return "ai/workflow/deploy"
    if normalized_action == "validate_existing_model" or normalized_path in {"tasks", "results"}:
        return "ai/workflow/results"
    if normalized_path in {"audit", "devices"}:
        return "ai/workflow/troubleshoot"
    return "ai"


def build_training_path(task_type: str | None) -> str:
    if task_type == "car_number_ocr":
        return "training/car-number-labeling"
    if task_type in {"inspection_mark_ocr", "performance_mark_ocr"}:
        return f"training/inspection-ocr/{task_type}"
    if task_type in {"door_lock_state_detect", "connector_defect_detect", "bolt_missing_detect"}:
        return f"training/inspection-state/{task_type}"
    return "training"
