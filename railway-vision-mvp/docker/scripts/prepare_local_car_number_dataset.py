#!/usr/bin/env python3
"""Prepare local car-number training bundles from demo_data/train."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


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


def _write_bundle(
    *,
    output_path: Path,
    split_name: str,
    image_paths: list[Path],
    annotations_by_file: dict[str, list[AnnotationRow]],
    class_names: list[str],
    dataset_key: str,
    dataset_label: str,
    source_dir: Path,
) -> dict:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    annotation_rows = [
        row
        for image_path in image_paths
        for row in annotations_by_file.get(image_path.name, [])
    ]
    records = [
        {
            "image_file": row.file_name,
            "label": class_names[row.class_index] if 0 <= row.class_index < len(class_names) else str(row.class_index),
            "bbox": [row.x1, row.y1, row.x2, row.y2],
            "class_index": row.class_index,
        }
        for row in annotation_rows
    ]
    manifest = {
        "dataset_key": dataset_key,
        "dataset_label": dataset_label,
        "task_type": "car_number_ocr",
        "split": split_name,
        "sample_count": len(image_paths),
        "annotation_count": len(annotation_rows),
        "class_names": class_names,
        "source_dir": str(source_dir),
        "generated_at": _utc_now_iso(),
        "annotation_format": "vistral_local_car_number_v1",
    }
    readme = (
        "Vistral local car-number dataset bundle\n"
        f"split={split_name}\n"
        f"samples={len(image_paths)}\n"
        f"annotations={len(annotation_rows)}\n"
        "images/ contains raw image files\n"
        "annotations/_annotations.txt keeps the original bbox format\n"
        "annotations/records.jsonl keeps structured rows for future trainers\n"
    )

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        zf.writestr("README.txt", readme)
        zf.writestr("annotations/_classes.txt", "\n".join(class_names) + ("\n" if class_names else ""))
        zf.writestr(
            "annotations/_annotations.txt",
            "".join(
                f"{row.file_name} {row.x1},{row.y1},{row.x2},{row.y2},{row.class_index}\n"
                for row in annotation_rows
            ),
        )
        zf.writestr(
            "annotations/records.jsonl",
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records),
        )
        for image_path in image_paths:
            zf.write(image_path, arcname=f"images/{image_path.name}")

    return {
        "split": split_name,
        "dataset_label": dataset_label,
        "dataset_key": dataset_key,
        "zip_path": str(output_path),
        "sample_count": len(image_paths),
        "annotation_count": len(annotation_rows),
    }


def build_bundles(
    *,
    source_dir: Path,
    output_dir: Path,
    train_ratio: float,
    seed: str,
) -> dict:
    classes_path = source_dir / "_classes.txt"
    annotations_path = source_dir / "_annotations.txt"
    class_names = _read_classes(classes_path)
    annotation_rows, empty_annotation_rows = _read_annotations(annotations_path)
    annotations_by_file: dict[str, list[AnnotationRow]] = defaultdict(list)
    for row in annotation_rows:
        annotations_by_file[row.file_name].append(row)

    image_paths = sorted(
        [path for path in source_dir.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS],
        key=lambda path: path.name,
    )
    if not image_paths:
        raise ValueError(f"no images found in {source_dir}")

    # 优先使用有标注的图片，避免把无效样本混进 OCR 训练集。
    # Prefer annotated samples for OCR training bundles.
    annotated_images = [path for path in image_paths if path.name in annotations_by_file]
    selected_images = annotated_images or image_paths
    if len(selected_images) < 2:
        raise ValueError("need at least 2 usable images to build train/validation splits")

    ranked = sorted(selected_images, key=lambda path: _stable_rank(path.name, seed))
    train_count = max(1, min(len(ranked) - 1, int(round(len(ranked) * train_ratio))))
    train_images = ranked[:train_count]
    validation_images = ranked[train_count:]
    dataset_key = "local-car-number-ocr"

    train_bundle = _write_bundle(
        output_path=output_dir / "car_number_ocr_train_bundle.zip",
        split_name="train",
        image_paths=train_images,
        annotations_by_file=annotations_by_file,
        class_names=class_names,
        dataset_key=dataset_key,
        dataset_label="local-car-number-train",
        source_dir=source_dir,
    )
    validation_bundle = _write_bundle(
        output_path=output_dir / "car_number_ocr_validation_bundle.zip",
        split_name="validation",
        image_paths=validation_images,
        annotations_by_file=annotations_by_file,
        class_names=class_names,
        dataset_key=dataset_key,
        dataset_label="local-car-number-validation",
        source_dir=source_dir,
    )

    summary = {
        "status": "ok",
        "generated_at": _utc_now_iso(),
        "source_dir": str(source_dir),
        "output_dir": str(output_dir),
        "total_images": len(image_paths),
        "annotated_images": len(annotated_images),
        "empty_annotation_rows": empty_annotation_rows,
        "selected_images": len(selected_images),
        "class_names": class_names,
        "train_ratio": train_ratio,
        "seed": seed,
        "bundles": {
            "train": train_bundle,
            "validation": validation_bundle,
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "car_number_ocr_dataset_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare local car-number OCR training bundles from demo_data/train.")
    parser.add_argument("--source-dir", default="demo_data/train", help="source image and annotation directory")
    parser.add_argument("--output-dir", default="demo_data/generated_datasets", help="output ZIP directory")
    parser.add_argument("--train-ratio", type=float, default=0.8, help="train split ratio, e.g. 0.8")
    parser.add_argument("--seed", default="vistral-local-car-number", help="stable split seed")
    args = parser.parse_args()

    source_dir = Path(args.source_dir).resolve()
    output_dir = Path(args.output_dir).resolve()
    if not source_dir.exists():
        raise SystemExit(f"source dir not found: {source_dir}")
    if not source_dir.is_dir():
        raise SystemExit(f"source path is not a directory: {source_dir}")
    if not (0.5 <= args.train_ratio < 1.0):
        raise SystemExit("train-ratio must be in [0.5, 1.0)")

    summary = build_bundles(
        source_dir=source_dir,
        output_dir=output_dir,
        train_ratio=args.train_ratio,
        seed=args.seed,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
