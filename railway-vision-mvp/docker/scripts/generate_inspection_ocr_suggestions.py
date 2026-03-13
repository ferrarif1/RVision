#!/usr/bin/env python3
"""Generate OCR suggestions for inspection/performance mark workspaces from prepared crop images."""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import cv2


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


def _tesseract_binary() -> str | None:
    return shutil.which("tesseract")


def _normalize_text(raw: str | None) -> str:
    value = str(raw or "").upper().replace(" ", "")
    value = re.sub(r"[^A-Z0-9./-]", "", value)
    value = re.sub(r"([./-]){2,}", r"\1", value)
    return value.strip("./-")


def _score_text(text: str, confidence: float) -> float:
    if not text:
        return -1.0
    length = len(text)
    digits = sum(ch.isdigit() for ch in text)
    letters = sum(ch.isalpha() for ch in text)
    alnum_ratio = sum(ch.isalnum() for ch in text) / max(length, 1)
    score = float(confidence)
    if 4 <= length <= 16:
        score += 0.35
    elif 3 <= length <= 20:
        score += 0.12
    else:
        score -= 0.22
    if digits and letters:
        score += 0.18
    elif digits or letters:
        score += 0.08
    score += alnum_ratio * 0.25
    if length <= 2:
        score -= 0.6
    return round(score, 4)


def _preprocess_variants(frame: Any) -> list[tuple[str, Any]]:
    if frame is None or not getattr(frame, "size", 0):
        return []
    gray = frame if len(frame.shape) == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    target_width = max(360, gray.shape[1] * 4)
    scale = min(12.0, max(2.0, target_width / max(gray.shape[1], 1)))
    resized = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    normalized = cv2.normalize(resized, None, 0, 255, cv2.NORM_MINMAX)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(normalized)
    blur = cv2.GaussianBlur(clahe, (3, 3), 0)
    sharpen = cv2.addWeighted(clahe, 1.4, blur, -0.4, 0)
    otsu = cv2.threshold(sharpen, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    inv_otsu = cv2.threshold(sharpen, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    adaptive = cv2.adaptiveThreshold(sharpen, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 11)
    return [
        ("gray", normalized),
        ("sharpen", sharpen),
        ("otsu", otsu),
        ("adaptive", adaptive),
    ]


def _try_tesseract(image: Any, *, psm: int) -> tuple[str, float] | None:
    binary = _tesseract_binary()
    if not binary or image is None or not getattr(image, "size", 0):
        return None
    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(prefix="vistral_inspection_ocr_", suffix=".png", delete=False) as handle:
            temp_path = handle.name
        if not cv2.imwrite(temp_path, image):
            return None
        proc = subprocess.run(
            [
                binary,
                temp_path,
                "stdout",
                "--psm",
                str(psm),
                "-c",
                "tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ-./",
            ],
            capture_output=True,
            check=False,
            timeout=8,
        )
        text = _normalize_text(proc.stdout.decode("utf-8", errors="ignore"))
    except Exception:
        return None
    finally:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)
    if not text:
        return None
    base_confidence = {6: 0.48, 7: 0.56, 8: 0.5, 13: 0.52}.get(psm, 0.45)
    return text, base_confidence


def _suggest_text(image_path: Path) -> dict[str, Any]:
    frame = cv2.imread(str(image_path))
    if frame is None or not getattr(frame, "size", 0):
        return {}
    scored: list[dict[str, Any]] = []
    for variant_name, variant in _preprocess_variants(frame):
        for psm in (7, 13, 6):
            result = _try_tesseract(variant, psm=psm)
            if not result:
                continue
            text, confidence = result
            scored.append(
                {
                    "text": text,
                    "confidence": confidence,
                    "quality": _score_text(text, confidence),
                    "engine": f"tesseract:{variant_name}:psm{psm}",
                }
            )
        if scored and max(item["quality"] for item in scored) >= 1.0:
            break
    if not scored:
        return {}
    best = max(scored, key=lambda item: (item["quality"], item["confidence"], len(item["text"])))
    if float(best["quality"]) < 0.4:
        return {}
    return best


def generate_suggestions(*, task_type: str, limit: int, force: bool) -> dict:
    blueprints = _load_blueprints()
    blueprint = blueprints.get(task_type)
    if not blueprint:
        raise ValueError(f"unsupported task_type: {task_type}")
    if str(blueprint.get("dataset_kind") or "").strip() != "ocr_text":
        raise ValueError(f"task_type is not OCR text: {task_type}")

    workspace_dir = _workspace_dir(task_type)
    manifest_csv = workspace_dir / "manifest.csv"
    manifest_jsonl = workspace_dir / "manifest.jsonl"
    fieldnames, rows = _load_manifest(manifest_csv)
    for extra in ["ocr_suggestion_confidence", "ocr_suggestion_quality", "ocr_suggestion_engine"]:
        if extra not in fieldnames:
            fieldnames.append(extra)

    updated = 0
    suggestion_rows = 0
    skipped_existing = 0
    skipped_missing_crop = 0
    engines: dict[str, int] = {}

    for row in rows:
        if str(row.get("final_text") or "").strip():
            if str(row.get("ocr_suggestion") or "").strip():
                suggestion_rows += 1
            continue
        if str(row.get("ocr_suggestion") or "").strip() and not force:
            suggestion_rows += 1
            skipped_existing += 1
            continue
        crop_file = str(row.get("crop_file") or "").strip()
        if not crop_file:
            skipped_missing_crop += 1
            continue
        crop_path = (workspace_dir / crop_file).resolve()
        if not crop_path.exists():
            skipped_missing_crop += 1
            continue
        suggestion = _suggest_text(crop_path)
        if suggestion.get("text"):
            row["ocr_suggestion"] = suggestion["text"]
            row["ocr_suggestion_confidence"] = str(suggestion.get("confidence") or "")
            row["ocr_suggestion_quality"] = str(suggestion.get("quality") or "")
            row["ocr_suggestion_engine"] = str(suggestion.get("engine") or "")
            engines[suggestion["engine"]] = engines.get(suggestion["engine"], 0) + 1
            suggestion_rows += 1
            updated += 1
        elif force:
            row["ocr_suggestion"] = ""
            row["ocr_suggestion_confidence"] = ""
            row["ocr_suggestion_quality"] = ""
            row["ocr_suggestion_engine"] = ""
        if limit and updated >= limit:
            break

    _save_manifest(manifest_csv, fieldnames, rows)
    _sync_manifest_jsonl(manifest_jsonl, rows)
    return {
        "status": "ok",
        "task_type": task_type,
        "updated_rows": updated,
        "suggestion_rows": suggestion_rows,
        "skipped_existing": skipped_existing,
        "skipped_missing_crop": skipped_missing_crop,
        "engines": engines,
        "manifest_csv": _display_path(manifest_csv),
        "manifest_jsonl": _display_path(manifest_jsonl),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate OCR suggestions for inspection OCR workspaces.")
    parser.add_argument("--task-type", required=True, help="inspection_mark_ocr or performance_mark_ocr")
    parser.add_argument("--limit", type=int, default=0, help="max rows to update; 0 means unlimited")
    parser.add_argument("--force", action="store_true", help="recompute rows with existing ocr_suggestion")
    args = parser.parse_args()

    summary = generate_suggestions(
        task_type=str(args.task_type).strip(),
        limit=max(int(args.limit or 0), 0),
        force=bool(args.force),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
