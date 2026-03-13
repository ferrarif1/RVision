#!/usr/bin/env python3
"""Bootstrap labeling workspaces for railcar inspection task families."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BLUEPRINT_PATH = REPO_ROOT / "config" / "railcar_inspection_dataset_blueprints.json"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT).as_posix())
    except Exception:
        return str(path)


def _load_blueprints() -> dict:
    payload = json.loads(BLUEPRINT_PATH.read_text(encoding="utf-8"))
    tasks = payload.get("tasks") or {}
    if not isinstance(tasks, dict) or not tasks:
        raise ValueError("inspection dataset blueprints are empty")
    return tasks


def _write_csv(path: Path, fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()


def _capture_plan_rows(*, task_type: str, blueprint: dict) -> list[dict[str, str]]:
    capture = blueprint.get("capture_profile") or {}
    qa_targets = blueprint.get("qa_targets") or {}
    dataset_kind = str(blueprint.get("dataset_kind") or "").strip()
    label_values = list(blueprint.get("label_values") or [])
    if dataset_kind == "ocr_text":
        shot_types = [
            ("clear", "清晰正样本"),
            ("light_stain", "轻污渍/轻锈蚀"),
            ("perspective", "透视畸变"),
            ("partial_occlusion", "局部遮挡"),
        ]
    else:
        shot_types = [(value, f"{value} 状态/缺陷") for value in (label_values or ["uncertain"])]
    target_min = int(blueprint.get("sample_target_min") or 0)
    per_bucket = max(target_min // max(len(shot_types), 1), 1)
    rows: list[dict[str, str]] = []
    for idx, (bucket_code, bucket_label) in enumerate(shot_types, start=1):
        rows.append(
            {
                "plan_id": f"{task_type}-{idx:03d}",
                "task_type": task_type,
                "task_label": str(blueprint.get("label") or task_type),
                "bucket_code": bucket_code,
                "bucket_label": bucket_label,
                "scene": str(capture.get("scene") or ""),
                "distance_m": json.dumps(capture.get("distance_m") or [], ensure_ascii=False),
                "view_angle_deg": str(capture.get("view_angle_deg") or ""),
                "image_quality": str(capture.get("image_quality") or ""),
                "target_count": str(per_bucket),
                "qa_targets": json.dumps(qa_targets, ensure_ascii=False),
                "notes": "按该桶位先采集可用真实样本，再进入 manifest.csv 复核与训练。",
            }
        )
    return rows


def bootstrap_workspace(*, task_type: str, output_dir: Path, force: bool) -> dict:
    blueprints = _load_blueprints()
    blueprint = blueprints.get(task_type)
    if not blueprint:
        raise ValueError(f"unsupported task_type: {task_type}")

    workspace_dir = output_dir / f"{task_type}_labeling"
    crops_dir = workspace_dir / "crops"
    crops_dir.mkdir(parents=True, exist_ok=True)

    fields = list(blueprint.get("recommended_fields") or [])
    if not fields:
        raise ValueError(f"blueprint missing recommended_fields: {task_type}")

    manifest_csv = workspace_dir / "manifest.csv"
    manifest_jsonl = workspace_dir / "manifest.jsonl"
    summary_json = workspace_dir / "summary.json"
    readme_md = workspace_dir / "README.md"
    capture_plan_csv = workspace_dir / "capture_plan.csv"

    if force or not manifest_csv.exists():
        _write_csv(manifest_csv, fields)
    if force or not capture_plan_csv.exists():
        capture_plan_fields = [
            "plan_id",
            "task_type",
            "task_label",
            "bucket_code",
            "bucket_label",
            "scene",
            "distance_m",
            "view_angle_deg",
            "image_quality",
            "target_count",
            "qa_targets",
            "notes",
        ]
        with capture_plan_csv.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=capture_plan_fields)
            writer.writeheader()
            writer.writerows(_capture_plan_rows(task_type=task_type, blueprint=blueprint))
    if force or not manifest_jsonl.exists():
        manifest_jsonl.write_text("", encoding="utf-8")

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
    }
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    notes = "\n".join(f"- {item}" for item in blueprint.get("notes") or [])
    label_values = "\n".join(f"- `{item}`" for item in blueprint.get("label_values") or [])
    structured_fields = "\n".join(f"- `{item}`\n" for item in blueprint.get("structured_fields") or [])
    capture_profile = blueprint.get("capture_profile") or {}
    qa_targets = blueprint.get("qa_targets") or {}
    readme_body = (
        f"# {blueprint.get('label')} 标注工作区\n\n"
        f"- task_type: `{task_type}`\n"
        f"- dataset_kind: `{blueprint.get('dataset_kind')}`\n"
        f"- dataset_key_prefix: `{blueprint.get('dataset_key_prefix')}`\n"
        f"- annotation_format: `{blueprint.get('annotation_format')}`\n"
        f"- 建议起步样本量: `{int(blueprint.get('sample_target_min') or 0)}`\n\n"
        + (
            "## 场景采集约束\n\n"
            f"- 场景: `{capture_profile.get('scene', '-')}`\n"
            f"- 建议距离: `{capture_profile.get('distance_m', '-')}`\n"
            f"- 建议角度: `{capture_profile.get('view_angle_deg', '-')}`\n"
            f"- 图像质量: `{capture_profile.get('image_quality', '-')}`\n"
            f"- 中心偏差上限: `{capture_profile.get('center_deviation_pct_max', '-')}`\n\n"
        )
        + (
        "## 目录说明\n\n"
        f"- `manifest.csv`: 主标注清单\n"
        f"- `manifest.jsonl`: JSONL 兼容清单\n"
        f"- `capture_plan.csv`: 采集计划模板\n"
        f"- `crops/`: 局部裁剪图或从原图导出的任务局部图\n"
        f"- `summary.json`: 当前工作区摘要\n\n"
        )
        + 
        "## manifest.csv 字段\n\n"
        + "".join(f"- `{field}`\n" for field in fields)
        + "\n## 推荐标签值\n\n"
        + (label_values or "- 无固定枚举，按 OCR 文本填写 `final_text`\n")
        + "\n## 推荐结构化字段\n\n"
        + (structured_fields or "- 当前任务没有额外结构化字段要求\n")
        + "\n## 首版验收目标\n\n"
        + "".join(f"- `{key}`: `{value}`\n" for key, value in qa_targets.items())
        + "\n## 标注建议\n\n"
        + (notes or "- 先补 source_file 与 split_hint，再逐步补全复核字段。\n")
    )
    readme_md.write_text(readme_body, encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap labeling workspace for railcar inspection task families.")
    parser.add_argument("--task-type", required=True, help="inspection task type, e.g. inspection_mark_ocr")
    parser.add_argument(
        "--output-dir",
        default="demo_data/generated_datasets",
        help="base directory to place generated labeling workspace",
    )
    parser.add_argument("--force", action="store_true", help="overwrite empty manifest/summary/readme")
    args = parser.parse_args()

    summary = bootstrap_workspace(
        task_type=str(args.task_type).strip(),
        output_dir=Path(args.output_dir).resolve(),
        force=bool(args.force),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
