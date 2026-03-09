#!/usr/bin/env python3
"""Build OCR text training bundles from reviewed car-number labeling manifests."""

from __future__ import annotations

import argparse
import csv
import json
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_name(value: str, fallback: str) -> str:
    clean = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "-" for ch in (value or "").strip())
    clean = clean.strip("-_")
    return clean or fallback


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT).as_posix())
    except Exception:
        return str(path)


def _load_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [dict(row) for row in reader]


def _pick_text(row: dict[str, str], *, allow_suggestions: bool) -> tuple[str, str]:
    final_text = str(row.get("final_text") or "").strip().upper()
    if final_text:
        return final_text, "final_text"
    if allow_suggestions:
        suggestion = str(row.get("ocr_suggestion") or "").strip().upper()
        if suggestion:
            return suggestion, "ocr_suggestion"
    return "", ""


def _write_bundle(
    *,
    rows: list[dict[str, str]],
    output_path: Path,
    split_name: str,
    dataset_key: str,
    dataset_label: str,
    source_manifest: Path,
) -> dict:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    records = []
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for row in rows:
            crop_rel = str(row.get("crop_file") or "").strip()
            crop_abs = source_manifest.parent / crop_rel
            if not crop_abs.exists():
                continue
            image_member = f"images/{Path(crop_rel).name}"
            zf.write(crop_abs, arcname=image_member)
            text_value = str(row.get("resolved_text") or "").strip()
            text_source = str(row.get("resolved_text_source") or "").strip()
            records.append(
                {
                    "sample_id": row.get("sample_id"),
                    "task_type": "car_number_ocr",
                    "label": row.get("label_class") or "number",
                    "text": text_value,
                    "text_source": text_source,
                    "image_file": image_member,
                    "source_file_name": row.get("source_file"),
                    "split_hint": row.get("split_hint"),
                    "review_status": row.get("review_status"),
                    "bbox": [
                        int(row.get("bbox_x1") or 0),
                        int(row.get("bbox_y1") or 0),
                        int(row.get("bbox_x2") or 0),
                        int(row.get("bbox_y2") or 0),
                    ],
                }
            )

        manifest = {
            "dataset_key": dataset_key,
            "dataset_label": dataset_label,
            "task_type": "car_number_ocr",
            "split": split_name,
            "sample_count": len(records),
            "annotation_count": len(records),
            "annotation_format": "vistral_local_car_number_text_v1",
            "generated_at": _utc_now_iso(),
            "source_manifest": str(source_manifest),
        }
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        zf.writestr(
            "README.txt",
            "Vistral local car-number text dataset bundle\n"
            f"split={split_name}\n"
            f"samples={len(records)}\n"
            "images/ contains cropped number regions\n"
            "annotations/records.jsonl contains OCR text labels\n",
        )
        zf.writestr(
            "annotations/records.jsonl",
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records),
        )
        zf.writestr(
            "annotations/transcriptions.csv",
            "sample_id,image_file,text,text_source,source_file_name,split_hint,review_status\n"
            + "".join(
                f"{item['sample_id']},{item['image_file']},{item['text']},{item['text_source']},{item['source_file_name']},{item['split_hint']},{item['review_status']}\n"
                for item in records
            ),
        )
    return {
        "split": split_name,
        "dataset_label": dataset_label,
        "dataset_key": dataset_key,
        "zip_path": _display_path(output_path),
        "sample_count": len(records),
        "annotation_count": len(records),
    }


def build_bundles(
    *,
    manifest_path: Path,
    output_dir: Path,
    allow_suggestions: bool,
) -> dict:
    rows = _load_rows(manifest_path)
    accepted: list[dict[str, str]] = []
    skipped_missing_text = 0
    source_counts = defaultdict(int)

    for row in rows:
        text_value, text_source = _pick_text(row, allow_suggestions=allow_suggestions)
        if not text_value:
            skipped_missing_text += 1
            continue
        item = dict(row)
        item["resolved_text"] = text_value
        item["resolved_text_source"] = text_source
        source_counts[text_source] += 1
        accepted.append(item)

    if len(accepted) < 2:
        raise ValueError("need at least 2 labeled rows to build train/validation bundles")

    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in accepted:
        grouped[str(row.get("split_hint") or "train")].append(row)

    train_rows = grouped.get("train", [])
    validation_rows = grouped.get("validation", [])
    if not train_rows or not validation_rows:
        raise ValueError("both train and validation rows are required in manifest")

    dataset_key = "local-car-number-ocr-text"
    bundle_train = _write_bundle(
        rows=train_rows,
        output_path=output_dir / "car_number_ocr_text_train_bundle.zip",
        split_name="train",
        dataset_key=dataset_key,
        dataset_label="local-car-number-text-train",
        source_manifest=manifest_path,
    )
    bundle_validation = _write_bundle(
        rows=validation_rows,
        output_path=output_dir / "car_number_ocr_text_validation_bundle.zip",
        split_name="validation",
        dataset_key=dataset_key,
        dataset_label="local-car-number-text-validation",
        source_manifest=manifest_path,
    )

    summary = {
        "status": "ok",
        "generated_at": _utc_now_iso(),
        "source_manifest": _display_path(manifest_path),
        "output_dir": _display_path(output_dir),
        "accepted_rows": len(accepted),
        "skipped_missing_text": skipped_missing_text,
        "text_sources": dict(source_counts),
        "bundles": {
            "train": bundle_train,
            "validation": bundle_validation,
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "car_number_ocr_text_dataset_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Build OCR text bundles from reviewed car-number labeling manifest.")
    parser.add_argument(
        "--manifest",
        default="demo_data/generated_datasets/car_number_ocr_labeling/manifest.csv",
        help="path to labeling manifest csv",
    )
    parser.add_argument(
        "--output-dir",
        default="demo_data/generated_datasets/car_number_ocr_text_dataset",
        help="output directory for OCR text bundles",
    )
    parser.add_argument(
        "--allow-suggestions",
        action="store_true",
        help="fallback to ocr_suggestion when final_text is empty",
    )
    args = parser.parse_args()

    manifest_path = Path(args.manifest).resolve()
    output_dir = Path(args.output_dir).resolve()
    summary = build_bundles(
        manifest_path=manifest_path,
        output_dir=output_dir,
        allow_suggestions=args.allow_suggestions,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
