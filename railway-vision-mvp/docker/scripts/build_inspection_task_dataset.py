#!/usr/bin/env python3
"""Build train/validation bundles from reviewed inspection-task labeling manifests."""

from __future__ import annotations

import argparse
import csv
import json
import zipfile
from collections import Counter, defaultdict
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


def _load_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _pick_text(row: dict[str, str], *, allow_suggestions: bool) -> tuple[str, str]:
    final_text = str(row.get("final_text") or "").strip().upper()
    if final_text:
        return final_text, "final_text"
    if allow_suggestions:
        suggestion = str(row.get("ocr_suggestion") or "").strip().upper()
        if suggestion:
            return suggestion, "ocr_suggestion"
    return "", ""


def _pick_label(row: dict[str, str], *, blueprint: dict) -> str:
    value = str(row.get("label_value") or row.get("final_label") or row.get("label_class") or "").strip()
    if not value:
        return ""
    accepted = {str(item).strip() for item in blueprint.get("label_values") or []}
    if accepted and value not in accepted:
        return ""
    return value


def _resolve_image_path(row: dict[str, str], *, manifest_path: Path) -> Path | None:
    crop_rel = str(row.get("crop_file") or "").strip()
    if crop_rel:
        crop_path = (manifest_path.parent / crop_rel).resolve()
        if crop_path.exists():
            return crop_path
    source_rel = str(row.get("source_file") or "").strip()
    if source_rel:
        source_path = (manifest_path.parent / source_rel).resolve()
        if source_path.exists():
            return source_path
        alt = (REPO_ROOT / source_rel).resolve()
        if alt.exists():
            return alt
    return None


def _write_bundle(
    *,
    rows: list[dict[str, str]],
    split_name: str,
    output_path: Path,
    source_manifest: Path,
    task_type: str,
    blueprint: dict,
) -> dict:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    dataset_key = f"{blueprint['dataset_key_prefix']}-{split_name}"
    dataset_label = f"{task_type}-{split_name}"
    dataset_kind = str(blueprint.get("dataset_kind") or "").strip()

    records = []
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for row in rows:
            image_path = _resolve_image_path(row, manifest_path=source_manifest)
            if not image_path:
                continue
            image_member = f"images/{image_path.name}"
            zf.write(image_path, arcname=image_member)
            record = {
                "sample_id": row.get("sample_id"),
                "task_type": task_type,
                "image_file": image_member,
                "source_file_name": row.get("source_file"),
                "crop_file": row.get("crop_file"),
                "split_hint": row.get("split_hint"),
                "review_status": row.get("review_status"),
                "bbox": [
                    int(row.get("bbox_x1") or 0),
                    int(row.get("bbox_y1") or 0),
                    int(row.get("bbox_x2") or 0),
                    int(row.get("bbox_y2") or 0),
                ],
                "notes": row.get("notes") or "",
            }
            if dataset_kind == "ocr_text":
                record["text"] = row.get("resolved_text")
                record["text_source"] = row.get("resolved_text_source")
                record["label"] = row.get("label_class") or "text"
            else:
                record["label"] = row.get("resolved_label")
                record["label_source"] = row.get("resolved_label_source")
            records.append(record)

        manifest = {
            "dataset_key": dataset_key,
            "dataset_label": dataset_label,
            "task_type": task_type,
            "split": split_name,
            "dataset_kind": dataset_kind,
            "sample_count": len(records),
            "annotation_count": len(records),
            "annotation_format": blueprint.get("annotation_format"),
            "generated_at": _utc_now_iso(),
            "source_manifest": _display_path(source_manifest),
            "label_values": list(blueprint.get("label_values") or []),
        }
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        zf.writestr(
            "README.txt",
            "Vistral railcar inspection dataset bundle\n"
            f"task_type={task_type}\n"
            f"split={split_name}\n"
            f"samples={len(records)}\n"
            f"dataset_kind={dataset_kind}\n"
            "images/ contains original or cropped images\n"
            "annotations/records.jsonl contains reviewed labels\n",
        )
        zf.writestr(
            "annotations/records.jsonl",
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records),
        )

    return {
        "split": split_name,
        "dataset_label": dataset_label,
        "dataset_key": dataset_key,
        "zip_path": _display_path(output_path),
        "sample_count": len(records),
        "annotation_count": len(records),
    }


def build_bundles(*, task_type: str, manifest_path: Path, output_dir: Path, allow_suggestions: bool) -> dict:
    blueprints = _load_blueprints()
    blueprint = blueprints.get(task_type)
    if not blueprint:
        raise ValueError(f"unsupported task_type: {task_type}")

    rows = _load_rows(manifest_path)
    accepted: list[dict[str, str]] = []
    skipped_missing_label = 0
    sources = Counter()
    reviewer_counts = Counter()
    dataset_kind = str(blueprint.get("dataset_kind") or "").strip()

    for row in rows:
        item = dict(row)
        if dataset_kind == "ocr_text":
            text_value, text_source = _pick_text(item, allow_suggestions=allow_suggestions)
            if not text_value:
                skipped_missing_label += 1
                continue
            item["resolved_text"] = text_value
            item["resolved_text_source"] = text_source
            sources[text_source] += 1
        else:
            label_value = _pick_label(item, blueprint=blueprint)
            if not label_value:
                skipped_missing_label += 1
                continue
            item["resolved_label"] = label_value
            item["resolved_label_source"] = "label_value"
            sources["label_value"] += 1
        reviewer = str(item.get("reviewer") or "").strip() or "unknown"
        reviewer_counts[reviewer] += 1
        accepted.append(item)

    if len(accepted) < 2:
        raise ValueError("need at least 2 reviewed rows to build train/validation bundles")

    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in accepted:
        grouped[str(row.get("split_hint") or "train")].append(row)

    train_rows = grouped.get("train", [])
    validation_rows = grouped.get("validation", [])
    if not train_rows or not validation_rows:
        raise ValueError("both train and validation rows are required in manifest")

    train_bundle = _write_bundle(
        rows=train_rows,
        split_name="train",
        output_path=output_dir / f"{task_type}_train_bundle.zip",
        source_manifest=manifest_path,
        task_type=task_type,
        blueprint=blueprint,
    )
    validation_bundle = _write_bundle(
        rows=validation_rows,
        split_name="validation",
        output_path=output_dir / f"{task_type}_validation_bundle.zip",
        source_manifest=manifest_path,
        task_type=task_type,
        blueprint=blueprint,
    )

    summary = {
        "status": "ok",
        "generated_at": _utc_now_iso(),
        "task_type": task_type,
        "task_label": blueprint.get("label"),
        "dataset_kind": dataset_kind,
        "source_manifest": _display_path(manifest_path),
        "output_dir": _display_path(output_dir),
        "accepted_rows": len(accepted),
        "skipped_missing_label": skipped_missing_label,
        "label_sources": dict(sources),
        "reviewer_counts": dict(reviewer_counts),
        "proxy_seeded_rows": int(reviewer_counts.get("proxy_from_car_number_truth") or 0),
        "bundles": {
            "train": train_bundle,
            "validation": validation_bundle,
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"{task_type}_dataset_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Build train/validation bundles from reviewed inspection-task manifests.")
    parser.add_argument("--task-type", required=True, help="inspection task type, e.g. inspection_mark_ocr")
    parser.add_argument("--manifest", required=True, help="path to reviewed manifest csv")
    parser.add_argument("--output-dir", required=True, help="output directory for train/validation bundles")
    parser.add_argument(
        "--allow-suggestions",
        action="store_true",
        help="for OCR tasks, fallback to ocr_suggestion when final_text is empty",
    )
    args = parser.parse_args()

    summary = build_bundles(
        task_type=str(args.task_type).strip(),
        manifest_path=Path(args.manifest).resolve(),
        output_dir=Path(args.output_dir).resolve(),
        allow_suggestions=bool(args.allow_suggestions),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
