#!/usr/bin/env python3
"""Refresh inspection labeling workspace summary.json files from current manifests."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BLUEPRINT_PATH = REPO_ROOT / "config" / "railcar_inspection_dataset_blueprints.json"
GENERATED_ROOT = REPO_ROOT / "demo_data" / "generated_datasets"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT).as_posix())
    except Exception:
        return str(path)


def _load_blueprints() -> dict[str, dict]:
    payload = json.loads(BLUEPRINT_PATH.read_text(encoding="utf-8"))
    tasks = payload.get("tasks") or {}
    if not isinstance(tasks, dict) or not tasks:
        raise ValueError("inspection dataset blueprints are empty")
    return tasks


def _load_manifest(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _review_status_counts(rows: list[dict[str, str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get("review_status") or "").strip() or "pending"
        counts[key] = counts.get(key, 0) + 1
    return counts


def _split_counts(rows: list[dict[str, str]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get("split_hint") or "").strip() or "train"
        counts[key] = counts.get(key, 0) + 1
    return counts


def _summarize_workspace(task_type: str, blueprint: dict) -> dict:
    workspace_dir = GENERATED_ROOT / f"{task_type}_labeling"
    manifest_csv = workspace_dir / "manifest.csv"
    manifest_jsonl = workspace_dir / "manifest.jsonl"
    capture_plan_csv = workspace_dir / "capture_plan.csv"
    crops_dir = workspace_dir / "crops"
    rows = _load_manifest(manifest_csv)

    crop_ready_rows = sum(1 for row in rows if str(row.get("crop_file") or "").strip())
    suggestion_rows = sum(1 for row in rows if str(row.get("ocr_suggestion") or "").strip())
    final_text_rows = sum(1 for row in rows if str(row.get("final_text") or "").strip())

    summary = {
        "status": "ok",
        "generated_at": _utc_now_iso(),
        "task_type": task_type,
        "task_label": blueprint.get("label"),
        "dataset_kind": blueprint.get("dataset_kind"),
        "dataset_key_prefix": blueprint.get("dataset_key_prefix"),
        "annotation_format": blueprint.get("annotation_format"),
        "sample_target_min": int(blueprint.get("sample_target_min") or 0),
        "sample_target_recommended": int(blueprint.get("sample_target_recommended") or 0),
        "label_values": list(blueprint.get("label_values") or []),
        "structured_fields": list(blueprint.get("structured_fields") or []),
        "capture_profile": blueprint.get("capture_profile") or {},
        "qa_targets": blueprint.get("qa_targets") or {},
        "review_status_values": list(blueprint.get("review_status_values") or []),
        "workspace_dir": _display_path(workspace_dir),
        "manifest_csv": _display_path(manifest_csv),
        "manifest_jsonl": _display_path(manifest_jsonl),
        "capture_plan_csv": _display_path(capture_plan_csv),
        "crops_dir": _display_path(crops_dir),
        "row_count": len(rows),
        "crop_ready_rows": crop_ready_rows,
        "suggestion_rows": suggestion_rows,
        "review_status_counts": _review_status_counts(rows),
        "final_text_rows": final_text_rows,
        "ready_rows": final_text_rows,
        "ready_ratio": round((final_text_rows / len(rows)), 4) if rows else 0.0,
        "split_counts": _split_counts(rows),
        "notes": list(blueprint.get("notes") or []),
    }
    return summary


def refresh_workspace_summary(task_type: str) -> dict:
    blueprints = _load_blueprints()
    blueprint = blueprints.get(task_type)
    if not blueprint:
        raise ValueError(f"unsupported task_type: {task_type}")
    workspace_dir = GENERATED_ROOT / f"{task_type}_labeling"
    summary_path = workspace_dir / "summary.json"
    summary = _summarize_workspace(task_type, blueprint)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh inspection workspace summary.json from manifest.csv")
    parser.add_argument("--task-type", action="append", help="specific task_type to refresh; may be passed multiple times")
    args = parser.parse_args()

    blueprints = _load_blueprints()
    task_types = args.task_type or list(blueprints.keys())
    results = [refresh_workspace_summary(str(task_type).strip()) for task_type in task_types]
    print(json.dumps({"status": "ok", "workspace_count": len(results), "items": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
