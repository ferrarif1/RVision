#!/usr/bin/env python3
"""Seed inspection-task labeling workspaces from real image files without fabricating labels."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BLUEPRINT_PATH = REPO_ROOT / "config" / "railcar_inspection_dataset_blueprints.json"


def _load_blueprints() -> dict:
    payload = json.loads(BLUEPRINT_PATH.read_text(encoding="utf-8"))
    tasks = payload.get("tasks") or {}
    if not isinstance(tasks, dict) or not tasks:
        raise ValueError("inspection dataset blueprints are empty")
    return tasks


def _workspace_dir(task_type: str) -> Path:
    return REPO_ROOT / "demo_data" / "generated_datasets" / f"{task_type}_labeling"


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT).as_posix())
    except Exception:
        return str(path)


def _load_manifest_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), [dict(row) for row in reader]


def _save_manifest_rows(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _stable_sample_id(task_type: str, rel_path: str) -> str:
    digest = hashlib.sha1(f"{task_type}:{rel_path}".encode("utf-8")).hexdigest()[:10]
    stem = Path(rel_path).stem.replace(" ", "_")
    return f"{stem}_{digest}"


def _split_hint(rel_path: str) -> str:
    digest = hashlib.sha1(rel_path.encode("utf-8")).hexdigest()
    return "validation" if int(digest[:2], 16) % 5 == 0 else "train"


def seed_workspace(
    *,
    task_type: str,
    source_dir: Path,
    glob_pattern: str,
    limit: int,
    label_class: str,
    notes: str,
    append: bool,
) -> dict:
    blueprints = _load_blueprints()
    blueprint = blueprints.get(task_type)
    if not blueprint:
        raise ValueError(f"unsupported task_type: {task_type}")

    workspace_dir = _workspace_dir(task_type)
    manifest_path = workspace_dir / "manifest.csv"
    if not manifest_path.exists():
        raise FileNotFoundError(f"workspace manifest not found: {manifest_path}")

    fieldnames, rows = _load_manifest_rows(manifest_path)
    existing_by_source = {str(row.get("source_file") or "").strip() for row in rows}
    if not append:
        rows = []
        existing_by_source = set()

    candidates = sorted(source_dir.rglob(glob_pattern))
    added = 0
    for image_path in candidates:
        if not image_path.is_file():
            continue
        rel_path = _display_path(image_path)
        if rel_path in existing_by_source:
            continue
        sample_id = _stable_sample_id(task_type, rel_path)
        row = {field: "" for field in fieldnames}
        row["sample_id"] = sample_id
        row["source_file"] = rel_path
        row["crop_file"] = ""
        row["split_hint"] = _split_hint(rel_path)
        row["task_type"] = task_type
        row["label_class"] = label_class or task_type
        row["review_status"] = "pending"
        row["notes"] = notes or "来自现有真实侧拍图，待人工挑选有效目标区域并补充标签。"
        rows.append(row)
        existing_by_source.add(rel_path)
        added += 1
        if limit and added >= limit:
            break

    _save_manifest_rows(manifest_path, fieldnames, rows)
    summary = {
        "status": "ok",
        "task_type": task_type,
        "dataset_kind": blueprint.get("dataset_kind"),
        "source_dir": _display_path(source_dir),
        "glob_pattern": glob_pattern,
        "added_rows": added,
        "total_rows": len(rows),
        "manifest_csv": _display_path(manifest_path),
    }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed inspection labeling workspaces from real image files.")
    parser.add_argument("--task-type", required=True, help="inspection task type")
    parser.add_argument("--source-dir", required=True, help="directory containing real source images")
    parser.add_argument("--glob", default="*.jpg", help="glob pattern under source-dir")
    parser.add_argument("--limit", type=int, default=0, help="max number of images to seed; 0 means unlimited")
    parser.add_argument("--label-class", default="", help="optional label_class value")
    parser.add_argument("--notes", default="", help="optional notes preset")
    parser.add_argument("--append", action="store_true", help="append instead of replacing current manifest rows")
    args = parser.parse_args()

    summary = seed_workspace(
        task_type=str(args.task_type).strip(),
        source_dir=Path(args.source_dir).resolve(),
        glob_pattern=str(args.glob).strip() or "*.jpg",
        limit=max(int(args.limit or 0), 0),
        label_class=str(args.label_class).strip(),
        notes=str(args.notes).strip(),
        append=bool(args.append),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
