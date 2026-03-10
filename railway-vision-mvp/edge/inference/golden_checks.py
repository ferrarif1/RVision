"""Golden fixture checks for built-in inference plugins.

Run:
  PYTHONPATH=edge python -m inference.golden_checks
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import cv2
import numpy as np

from inference.pipelines import ensure_plugins_loaded
from inference.pipelines import list_registered_plugins
from inference.pipelines import run_inference

KNOWN_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "railcar_number_known"
CURATED_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "railcar_number_curated"
CURATED_FIXTURE_IMAGE_DIR = CURATED_FIXTURE_DIR / "images"


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _build_fixture_assets(tmp_dir: str) -> tuple[str, str]:
    car_path = os.path.join(tmp_dir, "12345678_fixture.png")
    bolt_path = os.path.join(tmp_dir, "BOLT_EMPTY_fixture.png")

    car = np.full((360, 720, 3), 245, dtype=np.uint8)
    cv2.rectangle(car, (120, 120), (600, 220), (20, 20, 20), 2)
    cv2.putText(car, "12345678", (190, 190), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (20, 20, 20), 3)
    cv2.imwrite(car_path, car)

    bolt = np.full((360, 640, 3), 0, dtype=np.uint8)
    cv2.imwrite(bolt_path, bolt)
    return car_path, bolt_path


def run_golden_checks() -> dict:
    ensure_plugins_loaded()
    plugin_names = list_registered_plugins()
    _assert("object_detect" in plugin_names, "object_detect plugin missing")
    _assert("car_number_ocr" in plugin_names, "car_number_ocr plugin missing")
    _assert("bolt_missing_detect" in plugin_names, "bolt_missing_detect plugin missing")
    _assert("heuristic_router" in plugin_names, "heuristic_router plugin missing")

    with tempfile.TemporaryDirectory(prefix="vistral_golden_") as tmp_dir:
        car_path, bolt_path = _build_fixture_assets(tmp_dir)

        car_task = {
            "task_type": "car_number_ocr",
            "policy": {"upload_frames": False, "force_mock_ocr": True},
            "model": {"model_hash": "golden-car-hash"},
            "models": {
                "car-model": {
                    "id": "car-model",
                    "model_code": "car_number_ocr",
                    "version": "v-test",
                    "model_hash": "golden-car-hash",
                    "model_type": "expert",
                    "plugin_name": "car_number_ocr",
                }
            },
        }
        car_bundle = run_inference(
            car_task,
            car_path,
            model_artifacts={
                "car-model": {
                    "manifest": {"task_type": "car_number_ocr", "version": "v-test", "plugin_name": "car_number_ocr"},
                    "decrypted_path": "",
                    "model_hash": "golden-car-hash",
                }
            },
        )
        car_items = car_bundle["items"]
        _assert(len(car_items) >= 2, "car task produced no orchestrator result")
        car_result = next(item["result_json"] for item in car_items if item["result_json"].get("stage") == "expert")
        _assert(car_result["task_type"] == "car_number_ocr", "car task type mismatch")
        _assert(car_result["car_number"] == "12345678", "car number golden mismatch")
        _assert(car_result["engine"] == "mock", "car ocr engine should be mock in golden check")

        object_task = {
            "task_type": "object_detect",
            "policy": {
                "upload_frames": False,
                "quick_detect": {"object_prompt": "car"},
                "force_mock_object_detector": True,
            },
            "model": {"model_hash": "golden-object-hash"},
            "models": {
                "object-model": {
                    "id": "object-model",
                    "model_code": "object_detect",
                    "version": "v-test",
                    "model_hash": "golden-object-hash",
                    "model_type": "expert",
                    "plugin_name": "object_detect",
                }
            },
        }
        object_bundle = run_inference(
            object_task,
            car_path,
            model_artifacts={
                "object-model": {
                    "manifest": {"task_type": "object_detect", "version": "v-test", "plugin_name": "object_detect"},
                    "decrypted_path": "",
                    "model_hash": "golden-object-hash",
                }
            },
        )
        object_items = object_bundle["items"]
        _assert(len(object_items) >= 2, "object task produced no orchestrator result")
        object_result = next(item["result_json"] for item in object_items if item["result_json"].get("stage") == "expert")
        _assert(object_result["task_type"] == "object_detect", "object task type mismatch")
        _assert(object_result["object_prompt"] == "car", "object prompt golden mismatch")
        _assert(object_result["object_count"] >= 1, "object detector should emit at least one mocked box")
        _assert("car" in (object_result.get("matched_labels") or []), "object detector should match car label")

        bolt_task = {
            "task_type": "bolt_missing_detect",
            "policy": {"upload_frames": False, "force_fallback_detector": True},
            "model": {"model_hash": "golden-bolt-hash"},
            "models": {
                "bolt-model": {
                    "id": "bolt-model",
                    "model_code": "bolt_missing_detect",
                    "version": "v-test",
                    "model_hash": "golden-bolt-hash",
                    "model_type": "expert",
                    "plugin_name": "bolt_missing_detect",
                }
            },
        }
        bolt_bundle = run_inference(
            bolt_task,
            bolt_path,
            model_artifacts={
                "bolt-model": {
                    "manifest": {"task_type": "bolt_missing_detect", "version": "v-test", "plugin_name": "bolt_missing_detect"},
                    "decrypted_path": "",
                    "model_hash": "golden-bolt-hash",
                }
            },
        )
        bolt_items = bolt_bundle["items"]
        _assert(len(bolt_items) >= 2, "bolt task produced no orchestrator result")
        bolt_result = next(item["result_json"] for item in bolt_items if item["result_json"].get("stage") == "expert")
        _assert(bolt_result["task_type"] == "bolt_missing_detect", "bolt task type mismatch")
        _assert(isinstance(bolt_result["bolt_count"], int), "bolt_count should be integer")
        _assert(bolt_result["missing"] == (bolt_result["bolt_count"] == 0), "missing logic inconsistent with bolt_count")
        _assert(
            bolt_result["detector"] == "opencv_hough_circles_fallback",
            "bolt detector should be fallback in golden check",
        )

        curated_image = CURATED_FIXTURE_IMAGE_DIR / "3542_104_0_jpg.rf.0df66ec9ab0f91510738e2c6090c1f8d.jpg"
        if curated_image.exists():
            renamed_path = os.path.join(tmp_dir, "renamed_curated_probe.jpg")
            cv2.imwrite(renamed_path, cv2.imread(str(curated_image)))
            renamed_bundle = run_inference(
                car_task | {"policy": {"upload_frames": False}},
                renamed_path,
                model_artifacts={
                    "car-model": {
                        "manifest": {"task_type": "car_number_ocr", "version": "v-curated-fixture", "plugin_name": "car_number_ocr"},
                        "decrypted_path": "",
                        "model_hash": "golden-car-hash",
                    }
                },
            )
            renamed_expert = next(item["result_json"] for item in renamed_bundle["items"] if item["result_json"].get("stage") == "expert")
            _assert(renamed_expert["car_number"] == "61172052", "renamed curated image should still match reviewed railcar text")
            _assert(
                renamed_expert["bbox"] == [51, 164, 197, 250],
                f"renamed curated image bbox drifted: {renamed_expert['bbox']}",
            )

    fixture_results = {}
    manifest_path = KNOWN_FIXTURE_DIR / "manifest.json"
    if manifest_path.exists():
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        samples = payload.get("samples") or []
        for item in samples:
            if not isinstance(item, dict):
                continue
            file_name = str(item.get("file_name") or "").strip()
            label = str(item.get("label") or "").strip()
            if not file_name or not label:
                continue
            image_path = KNOWN_FIXTURE_DIR / file_name
            _assert(image_path.exists(), f"known fixture image missing: {file_name}")
            task = {
                "task_type": "car_number_ocr",
                "policy": {"upload_frames": False},
                "model": {"model_hash": "known-fixture-car-hash"},
                "models": {
                    "car-model": {
                        "id": "car-model",
                        "model_code": "car_number_ocr",
                        "version": "v-known-fixture",
                        "model_hash": "known-fixture-car-hash",
                        "model_type": "expert",
                        "plugin_name": "car_number_ocr",
                    }
                },
            }
            bundle = run_inference(
                task,
                str(image_path),
                model_artifacts={
                    "car-model": {
                        "manifest": {"task_type": "car_number_ocr", "version": "v-known-fixture", "plugin_name": "car_number_ocr"},
                        "decrypted_path": "",
                        "model_hash": "known-fixture-car-hash",
                    }
                },
            )
            expert = next(item_["result_json"] for item_ in bundle["items"] if item_["result_json"].get("stage") == "expert")
            actual = str(expert.get("car_number") or "")
            _assert(actual == label, f"known fixture mismatch for {file_name}: expected {label}, got {actual}")
            fixture_results[file_name] = actual

    return {
        "status": "ok",
        "plugins": plugin_names,
        "checks": {
            "object_detect": "passed",
            "car_number_ocr": "passed",
            "bolt_missing_detect": "passed",
            "curated_railcar_hash_match": "passed" if CURATED_FIXTURE_IMAGE_DIR.exists() else "skipped",
            "known_railcar_fixtures": f"{len(fixture_results)} passed" if fixture_results else "skipped",
        },
    }


def main() -> None:
    report = run_golden_checks()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
