#!/usr/bin/env python3
"""Create OCR labeling manifests and crops from demo_data/train annotations."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


@dataclass
class AnnotationRow:
    file_name: str
    x1: int
    y1: int
    x2: int
    y2: int
    class_index: int


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_classes(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _read_annotations(path: Path) -> tuple[list[AnnotationRow], int]:
    rows: list[AnnotationRow] = []
    empty_rows = 0
    if not path.exists():
        return rows, empty_rows
    for index, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        if " " not in line:
            empty_rows += 1
            continue
        try:
            file_name, bbox_csv = line.split(" ", 1)
            x1, y1, x2, y2, class_index = [int(part.strip()) for part in bbox_csv.split(",")]
        except Exception as exc:  # noqa: BLE001
            raise ValueError(f"invalid annotation line {index}: {line}") from exc
        rows.append(AnnotationRow(file_name=file_name, x1=x1, y1=y1, x2=x2, y2=y2, class_index=class_index))
    return rows, empty_rows


def _stable_rank(name: str, seed: str) -> str:
    return hashlib.sha1(f"{seed}:{name}".encode("utf-8")).hexdigest()


def _clamp_bbox(row: AnnotationRow, width: int, height: int) -> tuple[int, int, int, int]:
    x1 = max(0, min(int(row.x1), width - 1))
    y1 = max(0, min(int(row.y1), height - 1))
    x2 = max(x1 + 1, min(int(row.x2), width))
    y2 = max(y1 + 1, min(int(row.y2), height))
    return x1, y1, x2, y2


def _expand_bbox(x1: int, y1: int, x2: int, y2: int, width: int, height: int) -> tuple[int, int, int, int]:
    box_w = max(1, x2 - x1)
    box_h = max(1, y2 - y1)
    pad_x = max(6, int(box_w * 0.08))
    pad_top = max(4, int(box_h * 0.16))
    pad_bottom = max(6, int(box_h * 0.22))
    return (
        max(0, x1 - pad_x),
        max(0, y1 - pad_top),
        min(width, x2 + pad_x),
        min(height, y2 + pad_bottom),
    )


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT).as_posix())
    except Exception:
        return str(path)


CAR_NUMBER_DIGIT_SUBSTITUTIONS: dict[str, str] = {
    "O": "0",
    "Q": "0",
    "D": "0",
    "U": "0",
    "I": "1",
    "L": "1",
    "Z": "2",
    "E": "3",
    "A": "4",
    "S": "5",
    "G": "6",
    "T": "7",
    "B": "8",
}


def _clean_car_number_text(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _candidate_car_number_texts(raw_text: str | None) -> list[str]:
    cleaned = _clean_car_number_text(raw_text)
    if not cleaned:
        return []
    candidates = [cleaned]
    if len(cleaned) >= 6:
        mapped = "".join(CAR_NUMBER_DIGIT_SUBSTITUTIONS.get(char, char) for char in cleaned)
        if mapped and mapped not in candidates:
            candidates.append(mapped)
        if cleaned[:1].isalpha() and len(cleaned) >= 7:
            mapped_tail = cleaned[:1] + "".join(CAR_NUMBER_DIGIT_SUBSTITUTIONS.get(char, char) for char in cleaned[1:])
            if mapped_tail not in candidates:
                candidates.append(mapped_tail)
    return candidates


def _score_car_number_text(text: str | None, confidence: float = 0.0) -> float:
    cleaned = _clean_car_number_text(text)
    if not cleaned:
        return -1.0
    digits = sum(char.isdigit() for char in cleaned)
    letters = sum(char.isalpha() for char in cleaned)
    digit_ratio = digits / max(len(cleaned), 1)
    score = float(confidence)

    if re.fullmatch(r"\d{7,8}", cleaned):
        score += 0.9
    elif re.fullmatch(r"[A-Z]{1,3}\d{4,8}", cleaned):
        score += 0.55
    elif re.fullmatch(r"\d{6,10}", cleaned):
        score += 0.4
    elif re.fullmatch(r"[A-Z0-9]{6,10}", cleaned):
        score += 0.12
    else:
        score -= 0.2

    if 7 <= len(cleaned) <= 8:
        score += 0.3
    elif 6 <= len(cleaned) <= 10:
        score += 0.12
    else:
        score -= 0.25

    score += digit_ratio * 0.45
    if letters >= 2 and digit_ratio < 0.6:
        score -= 0.35
    if len(cleaned) <= 4:
        score -= 0.5
    return round(score, 4)


def _car_number_preprocess_variants(frame: Any) -> list[tuple[str, Any]]:
    if frame is None or not getattr(frame, "size", 0):
        return []
    gray = frame if len(frame.shape) == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    target_width = max(320, gray.shape[1] * 4)
    scale = min(12.0, max(2.0, target_width / max(gray.shape[1], 1)))
    resized = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    normalized = cv2.normalize(resized, None, 0, 255, cv2.NORM_MINMAX)
    blurred = cv2.GaussianBlur(normalized, (3, 3), 0)
    otsu = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    inv_otsu = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    adaptive = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 11)
    return [
        ("gray", normalized),
        ("otsu", otsu),
        ("inv_otsu", inv_otsu),
        ("adaptive", adaptive),
    ]


def _try_tesseract(image: Any, *, psm: int = 7) -> tuple[str, float] | None:
    binary = _tesseract_binary()
    if not binary:
        return None
    if image is None or not getattr(image, "size", 0):
        return None
    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(prefix="vistral_label_ocr_", suffix=".png", delete=False) as handle:
            temp_path = handle.name
        if not cv2.imwrite(temp_path, image):
            return None
        proc = subprocess.run(
            [binary, temp_path, "stdout", "--psm", str(psm), "-c", "tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"],
            capture_output=True,
            check=False,
        )
        text = _clean_car_number_text(proc.stdout.decode("utf-8", errors="ignore"))
    except Exception:
        return None
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)
    if not text:
        return None
    base_confidence = 0.56 if psm == 7 else 0.5
    return text, base_confidence


def _tesseract_binary() -> str | None:
    return shutil.which("tesseract")


def _suggest_text(crop: Any) -> dict[str, Any]:
    if crop is None or not getattr(crop, "size", 0):
        return {}

    scored: list[dict[str, Any]] = []
    try:
        for variant_name, variant in list(_car_number_preprocess_variants(crop))[:4]:
            tess_result = _try_tesseract(variant, psm=7) or _try_tesseract(variant, psm=8)
            if not tess_result:
                continue
            raw_text, confidence = tess_result
            for candidate in _candidate_car_number_texts(raw_text):
                scored.append(
                    {
                        "text": _clean_car_number_text(candidate),
                        "confidence": float(confidence),
                        "quality": float(_score_car_number_text(candidate, confidence)),
                        "engine": f"tesseract:{variant_name}",
                    }
                )
            if scored and max(item["quality"] for item in scored) >= 2.0:
                break
    except Exception:
        return {}

    scored = [item for item in scored if item.get("text")]
    if not scored:
        return {}
    best = max(scored, key=lambda item: (item["quality"], item["confidence"], len(item["text"])))
    if float(best["quality"]) < 0.6:
        return {}
    return best


def build_manifest(
    *,
    source_dir: Path,
    output_dir: Path,
    train_ratio: float,
    seed: str,
    with_suggestions: bool,
    max_rows: int | None = None,
    progress_every: int = 0,
) -> dict[str, Any]:
    class_names = _read_classes(source_dir / "_classes.txt")
    annotations, empty_rows = _read_annotations(source_dir / "_annotations.txt")
    image_names = sorted({row.file_name for row in annotations if row.file_name})
    if not image_names:
        raise ValueError(f"no annotated images found in {source_dir}")
    crops_dir = output_dir / "crops"
    crops_dir.mkdir(parents=True, exist_ok=True)
    manifest_jsonl = output_dir / "manifest.jsonl"
    manifest_csv = output_dir / "manifest.csv"
    readme_path = output_dir / "README.md"
    summary_path = output_dir / "summary.json"

    jsonl_lines: list[str] = []
    csv_rows: list[dict[str, Any]] = []
    suggestion_hits = 0
    ranked_names = sorted(image_names, key=lambda item: _stable_rank(item, seed))
    train_cutoff = max(1, min(len(ranked_names) - 1, int(round(len(ranked_names) * train_ratio))))
    train_names = set(ranked_names[:train_cutoff])

    for index, row in enumerate(annotations, start=1):
        if max_rows is not None and len(csv_rows) >= max_rows:
            break
        image_path = source_dir / row.file_name
        if image_path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        frame = cv2.imread(str(image_path))
        if frame is None or not getattr(frame, "size", 0):
            continue
        height, width = frame.shape[:2]
        x1, y1, x2, y2 = _clamp_bbox(row, width, height)
        crop_x1, crop_y1, crop_x2, crop_y2 = _expand_bbox(x1, y1, x2, y2, width, height)
        crop = frame[crop_y1:crop_y2, crop_x1:crop_x2]
        sample_id = f"{Path(row.file_name).stem}__{index:04d}"
        crop_file_name = f"{sample_id}.png"
        crop_path = crops_dir / crop_file_name
        cv2.imwrite(str(crop_path), crop)

        suggestion = _suggest_text(crop) if with_suggestions else {}
        if suggestion.get("text"):
            suggestion_hits += 1

        record = {
            "sample_id": sample_id,
            "split_hint": "train" if row.file_name in train_names else "validation",
            "source_file": row.file_name,
            "crop_file": str(crop_path.relative_to(output_dir).as_posix()),
            "label_class": class_names[row.class_index] if 0 <= row.class_index < len(class_names) else str(row.class_index),
            "image_width": width,
            "image_height": height,
            "bbox_x1": x1,
            "bbox_y1": y1,
            "bbox_x2": x2,
            "bbox_y2": y2,
            "crop_x1": crop_x1,
            "crop_y1": crop_y1,
            "crop_x2": crop_x2,
            "crop_y2": crop_y2,
            "ocr_suggestion": suggestion.get("text", ""),
            "ocr_suggestion_confidence": suggestion.get("confidence", ""),
            "ocr_suggestion_quality": suggestion.get("quality", ""),
            "ocr_suggestion_engine": suggestion.get("engine", ""),
            "final_text": "",
            "review_status": "pending",
            "reviewer": "",
            "notes": "",
        }
        jsonl_lines.append(json.dumps(record, ensure_ascii=False))
        csv_rows.append(record)
        if progress_every and len(csv_rows) % progress_every == 0:
            print(
                json.dumps(
                    {
                        "event": "progress",
                        "processed_rows": len(csv_rows),
                        "suggestion_rows": suggestion_hits,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_jsonl.write_text("\n".join(jsonl_lines) + ("\n" if jsonl_lines else ""), encoding="utf-8")
    fieldnames = list(csv_rows[0].keys()) if csv_rows else []
    with manifest_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(csv_rows)

    summary = {
        "status": "ok",
        "generated_at": _utc_now_iso(),
        "source_dir": _display_path(source_dir),
        "output_dir": _display_path(output_dir),
        "annotated_rows": len(csv_rows),
        "empty_annotation_rows": empty_rows,
        "suggestion_rows": suggestion_hits,
        "suggestion_ratio": round((suggestion_hits / len(csv_rows)), 4) if csv_rows else 0.0,
        "with_suggestions": bool(with_suggestions),
        "ocr_runtime_available": _tesseract_binary() is not None,
        "max_rows": max_rows,
        "seed": seed,
        "train_ratio": train_ratio,
        "files": {
            "manifest_jsonl": _display_path(manifest_jsonl),
            "manifest_csv": _display_path(manifest_csv),
            "readme": _display_path(readme_path),
            "summary": _display_path(summary_path),
            "crops_dir": _display_path(crops_dir),
        },
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    readme_path.write_text(
        "\n".join(
            [
                "# Local Car Number OCR Labeling Queue",
                "",
                "Generated from `demo_data/train/_annotations.txt`.",
                "",
                "Files:",
                "- `manifest.csv`: spreadsheet-friendly labeling queue",
                "- `manifest.jsonl`: machine-friendly version of the same queue",
                "- `crops/`: one crop per annotation row, padded slightly for easier review",
                "- `summary.json`: generation stats",
                "",
                "Suggested labeling flow:",
                "1. Open `manifest.csv` in a spreadsheet.",
                "2. Review `crop_file` in order and fill `final_text`.",
                "3. Keep `review_status` as `pending`, `done`, or `needs_check`.",
                "4. Leave the OCR suggestion columns untouched so we can measure suggestion quality later.",
                "",
                "Notes:",
                "- `split_hint` follows the current stable train/validation split seed.",
                "- OCR suggestions come from the current edge OCR helpers when available; blank means no reliable guess.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Create OCR labeling manifests and crops from demo_data/train.")
    parser.add_argument("--source-dir", default="demo_data/train", help="source image and annotation directory")
    parser.add_argument(
        "--output-dir",
        default="demo_data/generated_datasets/car_number_ocr_labeling",
        help="output directory for crops and manifest files",
    )
    parser.add_argument("--train-ratio", type=float, default=0.8, help="stable split ratio used for split_hint")
    parser.add_argument("--seed", default="vistral-local-car-number", help="stable split seed")
    parser.add_argument("--without-suggestions", action="store_true", help="skip OCR suggestion generation")
    parser.add_argument("--max-rows", type=int, default=0, help="limit rows for quick validation; 0 means all")
    parser.add_argument("--progress-every", type=int, default=0, help="print progress every N processed rows; 0 disables it")
    args = parser.parse_args()

    source_dir = (REPO_ROOT / args.source_dir).resolve() if not Path(args.source_dir).is_absolute() else Path(args.source_dir).resolve()
    output_dir = (REPO_ROOT / args.output_dir).resolve() if not Path(args.output_dir).is_absolute() else Path(args.output_dir).resolve()
    if not source_dir.exists() or not source_dir.is_dir():
        raise SystemExit(f"source dir not found: {source_dir}")
    if not (0.5 <= args.train_ratio < 1.0):
        raise SystemExit("train-ratio must be in [0.5, 1.0)")

    summary = build_manifest(
        source_dir=source_dir,
        output_dir=output_dir,
        train_ratio=args.train_ratio,
        seed=args.seed,
        with_suggestions=not args.without_suggestions,
        max_rows=args.max_rows or None,
        progress_every=max(0, args.progress_every),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
