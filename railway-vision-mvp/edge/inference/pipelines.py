from __future__ import annotations

import base64
import hashlib
import importlib
import json
import logging
import os
import re
import time
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Callable, Generator, Protocol

import cv2
import numpy as np

logger = logging.getLogger("edge-inference")


@dataclass(slots=True)
class ModelExecutionContext:
    task: dict[str, Any]
    local_asset_path: str
    model_path: str
    model_meta: dict[str, Any]
    manifest: dict[str, Any]
    pipeline: dict[str, Any]
    task_key: str
    context: dict[str, Any]
    options: dict[str, Any]
    policy: dict[str, Any]
    model_hash: str


class ModelPlugin(Protocol):
    plugin_names: tuple[str, ...]

    def run(self, ctx: ModelExecutionContext) -> dict[str, Any]:
        ...


_PLUGIN_REGISTRY: dict[str, ModelPlugin] = {}
_PLUGINS_INITIALIZED = False


def register_plugin(plugin: ModelPlugin) -> None:
    names = getattr(plugin, "plugin_names", ()) or ()
    if isinstance(names, str):
        names = (names,)
    names = tuple(str(name).strip() for name in names if str(name).strip())
    if not names:
        raise ValueError("plugin.plugin_names is required")
    for name in names:
        _PLUGIN_REGISTRY[name] = plugin


def list_registered_plugins() -> list[str]:
    return sorted(_PLUGIN_REGISTRY.keys())


def _parse_external_plugin_modules() -> list[str]:
    raw = os.getenv("EDGE_PLUGIN_MODULES", "").strip()
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def _load_external_plugins(register_fn: Callable[[ModelPlugin], None]) -> None:
    modules = _parse_external_plugin_modules()
    for module_name in modules:
        module = importlib.import_module(module_name)
        if hasattr(module, "register_plugins"):
            module.register_plugins(register_fn)
            logger.info("loaded external plugin module via register_plugins: %s", module_name)
            continue
        plugin_obj = getattr(module, "PLUGIN", None)
        if plugin_obj is not None:
            register_fn(plugin_obj)
            logger.info("loaded external plugin module via PLUGIN object: %s", module_name)
            continue
        raise RuntimeError(f"Invalid plugin module '{module_name}': missing register_plugins or PLUGIN")


def ensure_plugins_loaded() -> None:
    global _PLUGINS_INITIALIZED
    if _PLUGINS_INITIALIZED:
        return
    register_builtin_plugins()
    _load_external_plugins(register_plugin)
    _PLUGINS_INITIALIZED = True
    logger.info("inference plugins ready: %s", ", ".join(list_registered_plugins()))


def _resolve_plugin_name(model_meta: dict[str, Any], manifest: dict[str, Any]) -> str:
    return (
        str(model_meta.get("plugin_name") or "").strip()
        or str(manifest.get("plugin_name") or "").strip()
        or str(manifest.get("task_type") or "").strip()
        or str(model_meta.get("model_code") or "").strip()
    )


def _iter_frames(input_path: str, frame_step: int = 30, max_frames: int = 10) -> Generator[tuple[int, np.ndarray], None, None]:
    ext = os.path.splitext(input_path.lower())[1]
    if ext in {".jpg", ".jpeg", ".png", ".bmp"}:
        frame = cv2.imread(input_path)
        if frame is not None:
            yield 0, frame
        return

    cap = cv2.VideoCapture(input_path)
    idx = 0
    yielded = 0
    while cap.isOpened() and yielded < max_frames:
        ok, frame = cap.read()
        if not ok:
            break
        if idx % frame_step == 0:
            yield idx, frame
            yielded += 1
        idx += 1
    cap.release()


def _apply_pre_ops(frame: np.ndarray, ctx: ModelExecutionContext) -> np.ndarray:
    result = frame.copy()
    pre = ctx.pipeline.get("pre") if isinstance(ctx.pipeline.get("pre"), dict) else {}
    operations = list(pre.get("operations") or [])
    if ctx.context.get("camera_id"):
        operations.extend(pre.get("camera_overrides", {}).get(ctx.context.get("camera_id"), []))
    if ctx.context.get("scene_hint"):
        operations.extend(pre.get("scene_overrides", {}).get(ctx.context.get("scene_hint"), []))

    seen: set[str] = set()
    ordered = [op for op in operations if not (op in seen or seen.add(op))]
    for op in ordered:
        if op == "denoise":
            result = cv2.GaussianBlur(result, (5, 5), 1.2)
        elif op == "exposure_compensation":
            hsv = cv2.cvtColor(result, cv2.COLOR_BGR2HSV)
            hsv[:, :, 2] = cv2.equalizeHist(hsv[:, :, 2])
            result = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
        elif op == "sharpen":
            kernel = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
            result = cv2.filter2D(result, -1, kernel)
        elif op == "distortion_correction":
            # Placeholder for calibrated correction; current MVP keeps interface only.
            result = result
    return result


def _encode_frame_b64(frame: np.ndarray) -> str:
    ok, buffer = cv2.imencode(".jpg", frame)
    if not ok:
        return ""
    return base64.b64encode(buffer.tobytes()).decode("utf-8")


def _desensitize(frame: np.ndarray) -> np.ndarray:
    h, w = frame.shape[:2]
    if h < 20 or w < 20:
        return frame
    result = frame.copy()
    center = result[h // 4 : h * 3 // 4, w // 4 : w * 3 // 4]
    result[h // 4 : h * 3 // 4, w // 4 : w * 3 // 4] = cv2.GaussianBlur(center, (25, 25), 0)
    return result


def _preview_artifact(frame: np.ndarray) -> dict[str, Any]:
    return {"kind": "preview_frame", "mime": "image/jpeg", "content_b64": _encode_frame_b64(frame)}


def _strip_artifact_payloads(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned = []
    for artifact in artifacts:
        item = dict(artifact)
        item.pop("content_b64", None)
        cleaned.append(item)
    return cleaned


def _artifact_screenshot_b64(artifacts: list[dict[str, Any]]) -> str | None:
    for artifact in artifacts:
        if artifact.get("kind") == "preview_frame" and artifact.get("content_b64"):
            return str(artifact["content_b64"])
    return None


def _normalize_bbox(value: list[int] | tuple[int, int, int, int] | None) -> list[int] | None:
    if not value:
        return None
    return [int(value[0]), int(value[1]), int(value[2]), int(value[3])]


def _mock_car_number(file_name: str) -> str:
    matched = re.search(r"([A-Z]{1,3}\d{4,8})", file_name.upper())
    if matched:
        return matched.group(1)
    return "RV10086"


def _try_easyocr(frame: np.ndarray) -> tuple[str, float] | None:
    try:
        import easyocr  # type: ignore

        reader = easyocr.Reader(["en"], gpu=False)
        rs = reader.readtext(frame)
        if not rs:
            return None
        best = max(rs, key=lambda x: x[2])
        return str(best[1]), float(best[2])
    except Exception:
        return None


def _detect_bolts_fallback(frame: np.ndarray) -> tuple[int, list[list[int]]]:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 1.5)
    circles = cv2.HoughCircles(
        gray,
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=30,
        param1=100,
        param2=18,
        minRadius=5,
        maxRadius=30,
    )

    boxes: list[list[int]] = []
    if circles is not None:
        for c in np.round(circles[0, :]).astype(int):
            x, y, r = c.tolist()
            boxes.append([x - r, y - r, x + r, y + r])

    return len(boxes), boxes


MOBILENET_SSD_LABELS = [
    "background",
    "aeroplane",
    "bicycle",
    "bird",
    "boat",
    "bottle",
    "bus",
    "car",
    "cat",
    "chair",
    "cow",
    "diningtable",
    "dog",
    "horse",
    "motorbike",
    "person",
    "pottedplant",
    "sheep",
    "sofa",
    "train",
    "tvmonitor",
]


@lru_cache(maxsize=2)
def _prepare_model_bundle(bundle_path: str) -> tuple[str, str]:
    model_hash = hashlib.sha256(bundle_path.encode("utf-8")).hexdigest()[:16]
    out_dir = os.path.join("/tmp", "rv_open_models", model_hash)
    os.makedirs(out_dir, exist_ok=True)

    prototxt_path = os.path.join(out_dir, "deploy.prototxt")
    caffemodel_path = os.path.join(out_dir, "mobilenet_iter_73000.caffemodel")

    if os.path.exists(prototxt_path) and os.path.exists(caffemodel_path):
        return prototxt_path, caffemodel_path

    with zipfile.ZipFile(bundle_path) as zf:
        names = set(zf.namelist())
        if "deploy.prototxt" not in names or "mobilenet_iter_73000.caffemodel" not in names:
            raise RuntimeError("invalid model bundle files")
        zf.extract("deploy.prototxt", out_dir)
        zf.extract("mobilenet_iter_73000.caffemodel", out_dir)

    return prototxt_path, caffemodel_path


@lru_cache(maxsize=2)
def _load_mobilenet_ssd_net(bundle_path: str):
    prototxt_path, caffemodel_path = _prepare_model_bundle(bundle_path)
    return cv2.dnn.readNetFromCaffe(prototxt_path, caffemodel_path)


def _try_open_model_detect(frame: np.ndarray, model_path: str) -> tuple[int, list[list[Any]]] | None:
    if not model_path or not os.path.exists(model_path):
        return None
    try:
        net = _load_mobilenet_ssd_net(model_path)
        h, w = frame.shape[:2]
        blob = cv2.dnn.blobFromImage(cv2.resize(frame, (300, 300)), 0.007843, (300, 300), 127.5)
        net.setInput(blob)
        detections = net.forward()

        boxes: list[list[Any]] = []
        for i in range(detections.shape[2]):
            conf = float(detections[0, 0, i, 2])
            if conf < 0.45:
                continue
            class_id = int(detections[0, 0, i, 1])
            label = MOBILENET_SSD_LABELS[class_id] if 0 <= class_id < len(MOBILENET_SSD_LABELS) else f"cls_{class_id}"
            box = detections[0, 0, i, 3:7] * np.array([w, h, w, h])
            x1, y1, x2, y2 = box.astype("int").tolist()
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w - 1, x2), min(h - 1, y2)
            boxes.append([x1, y1, x2, y2, label, round(conf, 4)])
        return len(boxes), boxes
    except Exception:
        return None


class HeuristicRouterPlugin:
    plugin_names = ("heuristic_router", "scene_router", "router")

    def run(self, ctx: ModelExecutionContext) -> dict[str, Any]:
        started = time.time()
        asset_meta = (ctx.task.get("asset") or {}).get("meta") or {}
        search_text = " ".join(
            [
                os.path.basename(ctx.local_asset_path),
                str(ctx.context.get("scene_hint") or ""),
                str(ctx.task.get("task_type") or ""),
                str(asset_meta.get("use_case") or ""),
                str(asset_meta.get("dataset_label") or ""),
            ]
        ).lower()
        scores = {"car_number_ocr": 0.15, "bolt_missing_detect": 0.15}
        car_terms = ("car", "wagon", "ocr", "number", "车号", "车厢", "编号")
        bolt_terms = ("bolt", "missing", "螺栓", "紧固", "松动", "缺失")
        if any(term in search_text for term in car_terms):
            scores["car_number_ocr"] += 0.7
        if any(term in search_text for term in bolt_terms):
            scores["bolt_missing_detect"] += 0.7
        ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        tasks = [task for task, score in ordered if score >= 0.2]
        if not tasks:
            tasks = [ordered[0][0]]
        scene_id = tasks[0]
        scene_score = round(scores[scene_id], 4)
        return {
            "scene_id": scene_id,
            "scene_score": scene_score,
            "tasks": tasks,
            "task_scores": [round(scores[task], 4) for task in tasks],
            "predictions": [{"label": scene_id, "score": scene_score, "attributes": {"tasks": tasks}}],
            "artifacts": [],
            "metrics": {
                "duration_ms": int((time.time() - started) * 1000),
                "gpu_mem_mb": 0,
                "version": ctx.model_meta.get("version") or ctx.manifest.get("version"),
                "calibration": "heuristic",
            },
        }


class CarNumberOcrPlugin:
    plugin_names = ("car_number_ocr",)

    def run(self, ctx: ModelExecutionContext) -> dict[str, Any]:
        file_name = os.path.basename(ctx.local_asset_path)
        started = time.time()
        force_mock_ocr = bool((ctx.policy or {}).get("force_mock_ocr", False))
        predictions: list[dict[str, Any]] = []
        artifacts: list[dict[str, Any]] = []
        best_text = "-"
        best_score = 0.0
        best_bbox: list[int] | None = None
        best_engine = "mock"

        for frame_idx, raw_frame in _iter_frames(ctx.local_asset_path):
            frame = _apply_pre_ops(raw_frame, ctx)
            h, w = frame.shape[:2]
            x1, y1, x2, y2 = int(w * 0.2), int(h * 0.35), int(w * 0.8), int(h * 0.55)
            ocr = None if force_mock_ocr else _try_easyocr(frame[y1:y2, x1:x2])
            if ocr:
                text, conf = ocr
                engine = "easyocr"
            else:
                text, conf = _mock_car_number(file_name), 0.5
                engine = "mock"

            bbox = [x1, y1, x2, y2]
            predictions.append(
                {
                    "label": "car_number",
                    "score": round(float(conf), 4),
                    "bbox": bbox,
                    "text": text,
                    "attributes": {"frame_index": frame_idx, "engine": engine},
                }
            )
            if conf >= best_score:
                best_text = text
                best_score = float(conf)
                best_bbox = bbox
                best_engine = engine

            if not artifacts:
                annotated = frame.copy()
                cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(annotated, text, (x1, max(20, y1 - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
                if (ctx.policy or {}).get("desensitize_frames", False):
                    annotated = _desensitize(annotated)
                artifacts.append(_preview_artifact(annotated))

        return {
            "predictions": predictions,
            "artifacts": artifacts,
            "metrics": {
                "duration_ms": int((time.time() - started) * 1000),
                "gpu_mem_mb": 0,
                "version": ctx.model_meta.get("version") or ctx.manifest.get("version"),
                "calibration": "none",
            },
            "summary": {
                "task_type": "car_number_ocr",
                "car_number": best_text,
                "confidence": round(best_score, 4),
                "bbox": best_bbox,
                "engine": best_engine,
            },
        }


class BoltMissingDetectPlugin:
    plugin_names = ("bolt_missing_detect",)

    def run(self, ctx: ModelExecutionContext) -> dict[str, Any]:
        started = time.time()
        force_fallback_detector = bool((ctx.policy or {}).get("force_fallback_detector", False))
        predictions: list[dict[str, Any]] = []
        artifacts: list[dict[str, Any]] = []
        summary_box_count = 0
        summary_missing = False
        detector_name = "opencv_hough_circles_fallback"

        for frame_idx, raw_frame in _iter_frames(ctx.local_asset_path):
            frame = _apply_pre_ops(raw_frame, ctx)
            model_res = None if force_fallback_detector else _try_open_model_detect(frame, ctx.model_path)
            if model_res is not None:
                bolt_count, boxes = model_res
                detector_name = "opencv_mobilenet_ssd_bundle"
            else:
                bolt_count, boxes = _detect_bolts_fallback(frame)
                detector_name = "opencv_hough_circles_fallback"

            missing = bolt_count == 0
            summary_box_count = max(summary_box_count, int(bolt_count))
            summary_missing = summary_missing or missing
            predictions.append(
                {
                    "label": "bolt_missing" if missing else "bolt_present",
                    "score": 0.96 if missing else 0.78,
                    "bbox": None,
                    "attributes": {"frame_index": frame_idx, "bolt_count": bolt_count, "boxes": boxes, "detector": detector_name},
                }
            )

            if not artifacts:
                annotated = frame.copy()
                for box in boxes:
                    cv2.rectangle(annotated, (box[0], box[1]), (box[2], box[3]), (0, 200, 255), 2)
                    if len(box) >= 6:
                        label_text = f"{box[4]}:{box[5]:.2f}"
                        cv2.putText(annotated, label_text, (box[0], max(20, box[1] - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 1)
                cv2.putText(
                    annotated,
                    f"det_count={bolt_count}",
                    (20, 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.9,
                    (0, 0, 255) if missing else (0, 255, 0),
                    2,
                )
                if (ctx.policy or {}).get("desensitize_frames", False):
                    annotated = _desensitize(annotated)
                artifacts.append(_preview_artifact(annotated))

        return {
            "predictions": predictions,
            "artifacts": artifacts,
            "metrics": {
                "duration_ms": int((time.time() - started) * 1000),
                "gpu_mem_mb": 0,
                "version": ctx.model_meta.get("version") or ctx.manifest.get("version"),
                "calibration": "none",
            },
            "summary": {
                "task_type": "bolt_missing_detect",
                "bolt_count": summary_box_count,
                "missing": summary_missing,
                "detector": detector_name,
            },
        }


def register_builtin_plugins() -> None:
    register_plugin(HeuristicRouterPlugin())
    register_plugin(CarNumberOcrPlugin())
    register_plugin(BoltMissingDetectPlugin())


def _build_model_item(
    *,
    stage: str,
    task_key: str,
    pipeline: dict[str, Any] | None,
    model_meta: dict[str, Any],
    model_hash: str,
    execution: dict[str, Any],
) -> dict[str, Any]:
    artifacts = execution.get("artifacts") or []
    screenshot_b64 = _artifact_screenshot_b64(artifacts)
    result_json: dict[str, Any] = {
        "schema_version": "orchestrator.result.v1",
        "stage": stage,
        "task_type": task_key,
        "pipeline_id": (pipeline or {}).get("id"),
        "pipeline_code": (pipeline or {}).get("pipeline_code"),
        "model_type": model_meta.get("model_type"),
        "model_code": model_meta.get("model_code"),
        "predictions": execution.get("predictions") or [],
        "artifacts": _strip_artifact_payloads(artifacts),
        "metrics": execution.get("metrics") or {},
    }
    if stage == "router":
        result_json.update(
            {
                "scene_id": execution.get("scene_id"),
                "scene_score": execution.get("scene_score"),
                "tasks": execution.get("tasks") or [],
                "task_scores": execution.get("task_scores") or [],
            }
        )
    if isinstance(execution.get("summary"), dict):
        result_json.update(execution["summary"])

    alert_level = "ALERT" if any(pred.get("label") == "bolt_missing" for pred in (execution.get("predictions") or [])) else "INFO"
    return {
        "model_id": model_meta.get("id"),
        "model_hash": model_hash,
        "alert_level": alert_level,
        "duration_ms": (execution.get("metrics") or {}).get("duration_ms"),
        "screenshot_b64": screenshot_b64,
        "result_json": result_json,
    }


def _build_final_item(
    *,
    pipeline: dict[str, Any] | None,
    selected_tasks: list[str],
    router_output: dict[str, Any] | None,
    fused_predictions: list[dict[str, Any]],
    review_reasons: list[str],
    timings: dict[str, Any],
    screenshot_b64: str | None,
) -> dict[str, Any]:
    alert_level = "ALERT" if any(pred.get("label") == "bolt_missing" for pred in fused_predictions) else ("WARN" if review_reasons else "INFO")
    return {
        "model_id": None,
        "model_hash": router_output.get("metrics", {}).get("version", "pipeline") if router_output else "pipeline",
        "alert_level": alert_level,
        "duration_ms": timings.get("total_ms"),
        "screenshot_b64": screenshot_b64,
        "result_json": {
            "schema_version": "orchestrator.result.v1",
            "stage": "final",
            "task_type": "pipeline_orchestrated",
            "pipeline_id": (pipeline or {}).get("id"),
            "pipeline_code": (pipeline or {}).get("pipeline_code"),
            "scene_id": router_output.get("scene_id") if router_output else None,
            "scene_score": router_output.get("scene_score") if router_output else None,
            "selected_tasks": selected_tasks,
            "predictions": fused_predictions,
            "review_reasons": review_reasons,
            "timings": timings,
        },
    }


def _task_thresholds(pipeline: dict[str, Any], task_key: str) -> float:
    thresholds = pipeline.get("thresholds") if isinstance(pipeline.get("thresholds"), dict) else {}
    value = thresholds.get(task_key)
    if isinstance(value, dict):
        value = value.get("min_score")
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.45


def _human_review_reasons(
    *,
    pipeline: dict[str, Any],
    router_output: dict[str, Any] | None,
    fused_predictions: list[dict[str, Any]],
) -> list[str]:
    review = pipeline.get("human_review") if isinstance(pipeline.get("human_review"), dict) else {}
    if review.get("enabled") is False:
        return []

    reasons: list[str] = []
    fallback = ((pipeline.get("router") or {}).get("fallback") or {}) if isinstance(pipeline.get("router"), dict) else {}
    low_confidence_below = float(fallback.get("review_below", 0.55))
    if router_output and float(router_output.get("scene_score") or 0.0) < low_confidence_below:
        reasons.append(f"router_low_confidence<{low_confidence_below}")

    conditions = review.get("conditions") or []
    for condition in conditions:
        if not isinstance(condition, dict):
            continue
        if condition.get("type") == "low_confidence":
            below = float(condition.get("below", 0.5))
            if any(float(pred.get("score") or 0.0) < below for pred in fused_predictions):
                reasons.append(f"expert_low_confidence<{below}")
        if condition.get("type") == "no_prediction" and not fused_predictions:
            reasons.append("no_prediction")

    if not conditions and not fused_predictions:
        reasons.append("no_prediction")
    return reasons


def _fuse_predictions(
    pipeline: dict[str, Any],
    selected_tasks: list[str],
    expert_outputs: list[tuple[str, dict[str, Any], dict[str, Any]]],
) -> list[dict[str, Any]]:
    fusion = pipeline.get("fusion") if isinstance(pipeline.get("fusion"), dict) else {}
    strategy = str(fusion.get("strategy") or "priority").lower()
    max_experts_per_task = int(fusion.get("max_experts_per_task") or 2)

    per_task: dict[str, list[dict[str, Any]]] = {task_key: [] for task_key in selected_tasks}
    for task_key, _model_meta, execution in expert_outputs:
        predictions = list(execution.get("predictions") or [])
        threshold = _task_thresholds(pipeline, task_key)
        accepted = [pred for pred in predictions if float(pred.get("score") or 0.0) >= threshold]
        if strategy == "priority":
            per_task[task_key].extend(accepted[:max_experts_per_task])
        elif strategy == "vote":
            per_task[task_key].extend(accepted)
        else:
            per_task[task_key].extend(accepted)

    fused: list[dict[str, Any]] = []
    for task_key in selected_tasks:
        preds = per_task.get(task_key) or []
        if strategy == "vote":
            grouped: dict[str, list[dict[str, Any]]] = {}
            for pred in preds:
                grouped.setdefault(str(pred.get("label") or task_key), []).append(pred)
            for label, items in grouped.items():
                avg_score = round(sum(float(item.get("score") or 0.0) for item in items) / len(items), 4)
                seed = items[0]
                fused.append({**seed, "label": label, "score": avg_score, "attributes": {**(seed.get("attributes") or {}), "vote_count": len(items)}})
        else:
            fused.extend(preds)
    return fused


def _select_tasks(router_output: dict[str, Any] | None, pipeline: dict[str, Any], requested_task_type: str | None) -> list[str]:
    experts = pipeline.get("experts") if isinstance(pipeline.get("experts"), dict) else {}
    available_tasks = [str(key) for key in experts.keys()]
    if requested_task_type and requested_task_type in available_tasks:
        return [requested_task_type]
    if router_output and router_output.get("tasks"):
        tasks = []
        task_scores = router_output.get("task_scores") or []
        for index, task_key in enumerate(router_output.get("tasks") or []):
            score = float(task_scores[index]) if index < len(task_scores) else float(router_output.get("scene_score") or 0.0)
            if score >= _task_thresholds(pipeline, task_key):
                tasks.append(task_key)
        if tasks:
            return tasks
        fallback = ((pipeline.get("router") or {}).get("fallback") or {}) if isinstance(pipeline.get("router"), dict) else {}
        top_k = int(fallback.get("expand_top_k", 1) or 1)
        return [str(task) for task in (router_output.get("tasks") or [])[:top_k]]
    return available_tasks[:1]


def _run_model_plugin(
    *,
    task: dict[str, Any],
    local_asset_path: str,
    pipeline: dict[str, Any],
    task_key: str,
    context: dict[str, Any],
    options: dict[str, Any],
    policy: dict[str, Any],
    model_meta: dict[str, Any],
    artifacts: dict[str, Any],
) -> dict[str, Any]:
    manifest = artifacts.get("manifest") or {}
    plugin_name = _resolve_plugin_name(model_meta, manifest)
    plugin = _PLUGIN_REGISTRY.get(plugin_name)
    if not plugin:
        raise RuntimeError(f"unsupported plugin '{plugin_name}', available={list_registered_plugins()}")
    ctx = ModelExecutionContext(
        task=task,
        local_asset_path=local_asset_path,
        model_path=artifacts.get("decrypted_path") or "",
        model_meta=model_meta,
        manifest=manifest,
        pipeline=pipeline,
        task_key=task_key,
        context=context,
        options=options,
        policy=policy,
        model_hash=artifacts.get("model_hash") or model_meta.get("model_hash") or "",
    )
    return plugin.run(ctx)


def _input_hash(local_asset_path: str) -> str:
    sha = hashlib.sha256()
    with open(local_asset_path, "rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            sha.update(chunk)
    return sha.hexdigest()


def _legacy_pipeline(task: dict[str, Any]) -> dict[str, Any]:
    model = task.get("model") or {}
    models = task.get("models") if isinstance(task.get("models"), dict) else {}
    task_type = task.get("task_type")
    model_id = model.get("id")
    if not model_id and models:
        for candidate_id, candidate_meta in models.items():
            if not isinstance(candidate_meta, dict):
                continue
            if candidate_meta.get("model_code") == task_type or candidate_meta.get("plugin_name") == task_type:
                model_id = candidate_id
                break
        if not model_id:
            model_id = next(iter(models.keys()), None)
    if not model_id:
        return {"router": {}, "experts": {task_type: []}, "fusion": {"strategy": "priority", "max_experts_per_task": 1}, "thresholds": {}}
    return {
        # Direct-model fallback has no registry pipeline entity.
        "id": None,
        "pipeline_code": "legacy-single-model",
        "version": "v1",
        "router": {},
        "experts": {task_type: [{"model_id": model_id, "priority": 1}]},
        "fusion": {"strategy": "priority", "max_experts_per_task": 1},
        "thresholds": {},
        "human_review": {"enabled": False, "conditions": []},
    }


def _normalize_runtime_pipeline(raw_pipeline: dict[str, Any] | None) -> dict[str, Any]:
    pipeline = dict(raw_pipeline or {})
    config = pipeline.get("config") if isinstance(pipeline.get("config"), dict) else {}

    def _merged_dict(key: str, fallback: dict[str, Any] | None = None) -> dict[str, Any]:
        current = pipeline.get(key) if isinstance(pipeline.get(key), dict) else {}
        nested = config.get(key) if isinstance(config.get(key), dict) else {}
        base = fallback or {}
        return {**base, **nested, **current}

    experts = pipeline.get("experts") if isinstance(pipeline.get("experts"), dict) and pipeline.get("experts") else config.get("experts")
    thresholds = pipeline.get("thresholds") if isinstance(pipeline.get("thresholds"), dict) and pipeline.get("thresholds") else config.get("thresholds")
    fusion = pipeline.get("fusion") if isinstance(pipeline.get("fusion"), dict) and pipeline.get("fusion") else config.get("fusion")
    human_review = pipeline.get("human_review") if isinstance(pipeline.get("human_review"), dict) and pipeline.get("human_review") else config.get("human_review")

    pipeline["router"] = _merged_dict("router", {"fallback": {"mode": "human_review", "expand_top_k": 2}})
    pipeline["experts"] = experts if isinstance(experts, dict) else {}
    pipeline["thresholds"] = thresholds if isinstance(thresholds, dict) else {}
    pipeline["fusion"] = fusion if isinstance(fusion, dict) else {"strategy": "priority", "max_experts_per_task": 1}
    pipeline["pre"] = _merged_dict("pre")
    pipeline["post"] = _merged_dict("post")
    pipeline["human_review"] = human_review if isinstance(human_review, dict) else {"enabled": True, "conditions": []}
    if not pipeline.get("threshold_version"):
        pipeline["threshold_version"] = config.get("threshold_version")
    return pipeline


def run_inference(task: dict[str, Any], local_asset_path: str, model_artifacts: dict[str, Any]) -> dict[str, Any]:
    ensure_plugins_loaded()

    policy = task.get("policy") or {}
    orchestrator = (policy.get("orchestrator") or {}) if isinstance(policy.get("orchestrator"), dict) else {}
    context = dict(orchestrator.get("context") or {})
    options = dict(orchestrator.get("options") or {})
    pipeline = _normalize_runtime_pipeline(task.get("pipeline") or orchestrator.get("pipeline") or _legacy_pipeline(task))
    model_registry = dict(task.get("models") or {})

    started = time.time()
    items: list[dict[str, Any]] = []
    expert_outputs: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
    models_versions: list[dict[str, Any]] = []
    timings: dict[str, Any] = {"router_ms": 0, "experts_ms": {}, "total_ms": 0}

    for model_id, artifacts in model_artifacts.items():
        manifest = artifacts.get("manifest") or {}
        meta = model_registry.get(model_id) or {
            "id": model_id,
            "model_code": manifest.get("model_id"),
            "version": manifest.get("version"),
            "model_hash": artifacts.get("model_hash"),
            "model_type": manifest.get("model_type", "expert"),
            "plugin_name": manifest.get("plugin_name") or manifest.get("task_type"),
        }
        models_versions.append(
            {
                "model_id": model_id,
                "model_code": meta.get("model_code"),
                "model_type": meta.get("model_type"),
                "version": meta.get("version") or manifest.get("version"),
                "hash": artifacts.get("model_hash") or manifest.get("model_hash"),
            }
        )

    router_output = None
    router_conf = pipeline.get("router") if isinstance(pipeline.get("router"), dict) else {}
    router_model_id = router_conf.get("model_id")
    if router_model_id and router_model_id in model_artifacts:
        router_meta = model_registry.get(router_model_id) or {}
        router_output = _run_model_plugin(
            task=task,
            local_asset_path=local_asset_path,
            pipeline=pipeline,
            task_key="router",
            context=context,
            options=options,
            policy=policy,
            model_meta=router_meta,
            artifacts=model_artifacts[router_model_id],
        )
        timings["router_ms"] = (router_output.get("metrics") or {}).get("duration_ms", 0)
        items.append(
            _build_model_item(
                stage="router",
                task_key="router",
                pipeline=pipeline,
                model_meta=router_meta,
                model_hash=model_artifacts[router_model_id].get("model_hash") or router_meta.get("model_hash") or "",
                execution=router_output,
            )
        )

    selected_tasks = _select_tasks(router_output, pipeline, task.get("task_type"))
    for task_key in selected_tasks:
        bindings = list((pipeline.get("experts") or {}).get(task_key) or [])
        for binding in bindings[: int((pipeline.get("fusion") or {}).get("max_experts_per_task", 2) or 2)]:
            model_id = binding.get("model_id")
            if not model_id or model_id not in model_artifacts:
                continue
            model_meta = model_registry.get(model_id) or {}
            execution = _run_model_plugin(
                task=task,
                local_asset_path=local_asset_path,
                pipeline=pipeline,
                task_key=task_key,
                context=context,
                options=options,
                policy=policy,
                model_meta=model_meta,
                artifacts=model_artifacts[model_id],
            )
            timings["experts_ms"][model_id] = (execution.get("metrics") or {}).get("duration_ms", 0)
            expert_outputs.append((task_key, model_meta, execution))
            items.append(
                _build_model_item(
                    stage="expert",
                    task_key=task_key,
                    pipeline=pipeline,
                    model_meta=model_meta,
                    model_hash=model_artifacts[model_id].get("model_hash") or model_meta.get("model_hash") or "",
                    execution=execution,
                )
            )

    fused_predictions = _fuse_predictions(pipeline, selected_tasks, expert_outputs)
    review_reasons = _human_review_reasons(pipeline=pipeline, router_output=router_output, fused_predictions=fused_predictions)

    final_screenshot = next((item.get("screenshot_b64") for item in items if item.get("screenshot_b64")), None)
    timings["total_ms"] = int((time.time() - started) * 1000)
    items.append(
        _build_final_item(
            pipeline=pipeline,
            selected_tasks=selected_tasks,
            router_output=router_output,
            fused_predictions=fused_predictions,
            review_reasons=review_reasons,
            timings=timings,
            screenshot_b64=final_screenshot,
        )
    )

    run_payload = {
        "job_id": task.get("task_id"),
        "pipeline_id": pipeline.get("id"),
        "pipeline_version": pipeline.get("version"),
        "threshold_version": pipeline.get("threshold_version") or (pipeline.get("config") or {}).get("threshold_version"),
        "input_hash": _input_hash(local_asset_path),
        "input_summary": {
            "asset_id": (task.get("asset") or {}).get("id"),
            "scene_hint": context.get("scene_hint"),
            "device_code": task.get("device_code"),
            "camera_id": context.get("camera_id"),
        },
        "models_versions": models_versions,
        "timings": timings,
        "result_summary": {
            "scene_id": router_output.get("scene_id") if router_output else None,
            "scene_score": router_output.get("scene_score") if router_output else None,
            "selected_tasks": selected_tasks,
            "prediction_count": len(fused_predictions),
            "review_reasons": review_reasons,
        },
        "review_reasons": review_reasons,
    }
    return {"items": items, "run": run_payload}
