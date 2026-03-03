"""Golden fixture checks for built-in inference plugins.

Run:
  PYTHONPATH=edge python -m inference.golden_checks
"""

from __future__ import annotations

import json
import os
import tempfile

import cv2
import numpy as np

from inference.pipelines import ensure_plugins_loaded
from inference.pipelines import list_registered_plugins
from inference.pipelines import run_inference


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _build_fixture_assets(tmp_dir: str) -> tuple[str, str]:
    car_path = os.path.join(tmp_dir, "CAR123456_fixture.png")
    bolt_path = os.path.join(tmp_dir, "BOLT_EMPTY_fixture.png")

    car = np.full((360, 720, 3), 245, dtype=np.uint8)
    cv2.rectangle(car, (120, 120), (600, 220), (20, 20, 20), 2)
    cv2.putText(car, "CAR123456", (170, 190), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (20, 20, 20), 3)
    cv2.imwrite(car_path, car)

    bolt = np.full((360, 640, 3), 0, dtype=np.uint8)
    cv2.imwrite(bolt_path, bolt)
    return car_path, bolt_path


def run_golden_checks() -> dict:
    ensure_plugins_loaded()
    plugin_names = list_registered_plugins()
    _assert("car_number_ocr" in plugin_names, "car_number_ocr plugin missing")
    _assert("bolt_missing_detect" in plugin_names, "bolt_missing_detect plugin missing")
    _assert("heuristic_router" in plugin_names, "heuristic_router plugin missing")

    with tempfile.TemporaryDirectory(prefix="rv_golden_") as tmp_dir:
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
        _assert(car_result["car_number"] == "CAR123456", "car number golden mismatch")
        _assert(car_result["engine"] == "mock", "car ocr engine should be mock in golden check")

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

    return {
        "status": "ok",
        "plugins": plugin_names,
        "checks": {
            "car_number_ocr": "passed",
            "bolt_missing_detect": "passed",
        },
    }


def main() -> None:
    report = run_golden_checks()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
