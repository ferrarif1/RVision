#!/usr/bin/env python3
"""Prepare proxy OCR crops for inspection/performance mark workspaces from existing side-view annotations."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[2]
BLUEPRINT_PATH = REPO_ROOT / "config" / "railcar_inspection_dataset_blueprints.json"
ANNOTATION_PATH = REPO_ROOT / "demo_data" / "train" / "_annotations.txt"


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


def _load_manifest(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), [dict(row) for row in reader]


def _save_manifest(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _sync_manifest_jsonl(path: Path, rows: list[dict[str, str]]) -> None:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def _load_anchor_bboxes(path: Path) -> dict[str, tuple[int, int, int, int]]:
    if not path.exists():
        raise FileNotFoundError(path)
    mapping: dict[str, tuple[int, int, int, int]] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        file_name, _, bbox_raw = line.partition(" ")
        if not file_name or not bbox_raw:
            continue
        coords = [int(float(item)) for item in bbox_raw.split(",")[:4]]
        if len(coords) == 4:
            mapping[file_name] = tuple(coords)
    return mapping


def _expand_bbox(
    *,
    bbox: tuple[int, int, int, int],
    image_width: int,
    image_height: int,
    profile: dict,
) -> tuple[int, int, int, int]:
    mode = str(profile.get("mode") or "").strip()
    x1, y1, x2, y2 = bbox
    width = max(x2 - x1, 1)
    height = max(y2 - y1, 1)

    if mode == "relative_window":
        crop_width = max(1, int(round(width * float(profile.get("window_width_ratio", 1.0)))))
        crop_height = max(1, int(round(height * float(profile.get("window_height_ratio", 1.0)))))
        center_x = x1 + width * float(profile.get("window_center_x_ratio", 0.5))
        center_y = y1 + height * float(profile.get("window_center_y_ratio", 0.5))
        left = int(round(center_x - crop_width / 2))
        right = left + crop_width
        top = int(round(center_y - crop_height / 2))
        bottom = top + crop_height
    else:
        left = int(round(x1 - width * float(profile.get("expand_left_ratio", 0.0))))
        right = int(round(x2 + width * float(profile.get("expand_right_ratio", 0.0))))
        top = int(round(y1 - height * float(profile.get("expand_top_ratio", 0.0))))
        bottom = int(round(y2 + height * float(profile.get("expand_bottom_ratio", 0.0))))

    min_width = int(round(image_width * float(profile.get("min_crop_width_ratio", 0.0))))
    min_height = int(round(image_height * float(profile.get("min_crop_height_ratio", 0.0))))
    if min_width and (right - left) < min_width:
        pad = (min_width - (right - left)) // 2 + 1
        left -= pad
        right += pad
    if min_height and (bottom - top) < min_height:
        pad = (min_height - (bottom - top)) // 2 + 1
        top -= pad
        bottom += pad

    return (
        max(0, min(left, image_width - 1)),
        max(0, min(top, image_height - 1)),
        max(1, min(right, image_width)),
        max(1, min(bottom, image_height)),
    )


def prepare_proxy_crops(*, task_type: str, annotation_path: Path, limit: int, force: bool) -> dict:
    blueprints = _load_blueprints()
    blueprint = blueprints.get(task_type)
    if not blueprint:
        raise ValueError(f"unsupported task_type: {task_type}")
    if str(blueprint.get("dataset_kind") or "").strip() != "ocr_text":
        raise ValueError(f"task_type is not OCR text: {task_type}")

    profile = blueprint.get("proxy_crop_profile") or {}
    if not profile:
        raise ValueError(f"proxy_crop_profile missing for task_type: {task_type}")

    workspace_dir = _workspace_dir(task_type)
    manifest_csv = workspace_dir / "manifest.csv"
    manifest_jsonl = workspace_dir / "manifest.jsonl"
    crops_dir = workspace_dir / "crops"
    crops_dir.mkdir(parents=True, exist_ok=True)

    fieldnames, rows = _load_manifest(manifest_csv)
    anchor_bboxes = _load_anchor_bboxes(annotation_path)

    prepared = 0
    skipped_existing = 0
    skipped_missing_anchor = 0

    for row in rows:
        if str(row.get("crop_file") or "").strip() and not force:
            skipped_existing += 1
            continue
        source_file = str(row.get("source_file") or "").strip()
        if not source_file:
            continue
        source_path = (REPO_ROOT / source_file).resolve()
        if not source_path.exists():
            continue
        anchor_bbox = anchor_bboxes.get(source_path.name)
        if not anchor_bbox:
            skipped_missing_anchor += 1
            continue

        with Image.open(source_path) as image:
            image = image.convert("RGB")
            crop_bbox = _expand_bbox(
                bbox=anchor_bbox,
                image_width=image.width,
                image_height=image.height,
                profile=profile,
            )
            crop = image.crop(crop_bbox)
            crop_name = f"{(row.get('sample_id') or source_path.stem).strip() or source_path.stem}{source_path.suffix.lower() or '.jpg'}"
            crop_path = crops_dir / crop_name
            crop.save(crop_path, quality=95)

        row["crop_file"] = f"crops/{crop_name}"
        row["bbox_x1"] = str(crop_bbox[0])
        row["bbox_y1"] = str(crop_bbox[1])
        row["bbox_x2"] = str(crop_bbox[2])
        row["bbox_y2"] = str(crop_bbox[3])
        if str(row.get("review_status") or "").strip() in {"", "pending"}:
            row["review_status"] = "needs_check"
        proxy_note = "已根据现有车身编号框生成代理裁剪，需人工确认并微调文字区域。"
        notes = str(row.get("notes") or "").strip()
        if proxy_note not in notes:
            row["notes"] = f"{notes} {proxy_note}".strip()
        prepared += 1
        if limit and prepared >= limit:
            break

    _save_manifest(manifest_csv, fieldnames, rows)
    _sync_manifest_jsonl(manifest_jsonl, rows)
    return {
        "status": "ok",
        "task_type": task_type,
        "prepared_rows": prepared,
        "skipped_existing_crop": skipped_existing,
        "skipped_missing_anchor": skipped_missing_anchor,
        "manifest_csv": _display_path(manifest_csv),
        "manifest_jsonl": _display_path(manifest_jsonl),
        "crops_dir": _display_path(crops_dir),
        "annotation_source": _display_path(annotation_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare proxy OCR crops from existing side-view bbox annotations.")
    parser.add_argument("--task-type", required=True, help="inspection_mark_ocr or performance_mark_ocr")
    parser.add_argument("--annotation-file", default=str(ANNOTATION_PATH), help="annotation txt file")
    parser.add_argument("--limit", type=int, default=0, help="max number of rows to prepare; 0 means unlimited")
    parser.add_argument("--force", action="store_true", help="overwrite existing crop_file values")
    args = parser.parse_args()

    summary = prepare_proxy_crops(
        task_type=str(args.task_type).strip(),
        annotation_path=Path(args.annotation_file).resolve(),
        limit=max(int(args.limit or 0), 0),
        force=bool(args.force),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
