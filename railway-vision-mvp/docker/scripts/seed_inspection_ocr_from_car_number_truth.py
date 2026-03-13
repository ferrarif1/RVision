#!/usr/bin/env python3
"""Seed inspection OCR manifests from reviewed car-number truths on the same source image."""

from __future__ import annotations

import argparse
import csv
import json
import os
from collections import Counter
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
GENERATED_ROOT = REPO_ROOT / "demo_data" / "generated_datasets"
CAR_NUMBER_MANIFEST = GENERATED_ROOT / "car_number_ocr_labeling" / "manifest.csv"
SUPPORTED_TASKS = ("inspection_mark_ocr", "performance_mark_ocr")
PROXY_REVIEWER = "proxy_from_car_number_truth"


def _load_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [dict(row) for row in reader]
        return list(reader.fieldnames or []), rows


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_jsonl(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _car_truth_map() -> dict[str, str]:
    _, rows = _load_csv(CAR_NUMBER_MANIFEST)
    truth_map: dict[str, str] = {}
    for row in rows:
        final_text = str(row.get("final_text") or "").strip().upper()
        review_status = str(row.get("review_status") or "").strip().lower()
        if not final_text or review_status != "done":
            continue
        truth_map[os.path.basename(str(row.get("source_file") or "").strip())] = final_text
    return truth_map


def _seed_task(task_type: str, *, truth_map: dict[str, str], overwrite: bool) -> dict[str, int]:
    workspace = GENERATED_ROOT / f"{task_type}_labeling"
    manifest_csv = workspace / "manifest.csv"
    manifest_jsonl = workspace / "manifest.jsonl"
    fieldnames, rows = _load_csv(manifest_csv)
    stats = Counter(total=len(rows))
    for row in rows:
        source_base = os.path.basename(str(row.get("source_file") or "").strip())
        truth = truth_map.get(source_base)
        if not truth:
            stats["no_truth_match"] += 1
            continue
        current_text = str(row.get("final_text") or "").strip()
        if current_text and not overwrite:
            stats["kept_existing"] += 1
            continue
        row["final_text"] = truth
        row["review_status"] = "done"
        row["reviewer"] = PROXY_REVIEWER
        existing_notes = str(row.get("notes") or "").strip()
        proxy_note = "代理导入：复用同图已复核车号真值，作为巡检 OCR 首版代理文本。"
        row["notes"] = f"{existing_notes} {proxy_note}".strip() if existing_notes else proxy_note
        stats["seeded"] += 1
    _write_csv(manifest_csv, fieldnames, rows)
    _write_jsonl(manifest_jsonl, rows)
    return dict(stats)


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed inspection OCR manifests from reviewed car-number truths.")
    parser.add_argument(
        "--task-type",
        action="append",
        choices=SUPPORTED_TASKS,
        help="Task type to seed. Omit to seed all supported tasks.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing final_text values if present.",
    )
    args = parser.parse_args()

    task_types = args.task_type or list(SUPPORTED_TASKS)
    truth_map = _car_truth_map()
    if not truth_map:
        raise SystemExit("no reviewed car-number truths found")

    summary = {
        "status": "ok",
        "source_truth_rows": len(truth_map),
        "tasks": {},
    }
    for task_type in task_types:
        summary["tasks"][task_type] = _seed_task(task_type, truth_map=truth_map, overwrite=args.overwrite)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
