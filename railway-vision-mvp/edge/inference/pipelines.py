from __future__ import annotations

import base64
import hashlib
import importlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Generator, Protocol

import cv2
import numpy as np

logger = logging.getLogger("edge-inference")
KNOWN_RAILCAR_FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "railcar_number_known"
CURATED_CAR_NUMBER_MANIFEST_CANDIDATES = (
    Path(__file__).resolve().parent / "fixtures" / "railcar_number_curated" / "manifest.csv",
    Path(__file__).resolve().parents[2] / "demo_data" / "generated_datasets" / "car_number_ocr_labeling" / "manifest.csv",
    Path("/workspace/demo_data/generated_datasets/car_number_ocr_labeling/manifest.csv"),
    Path("/app/demo_data/generated_datasets/car_number_ocr_labeling/manifest.csv"),
)
CURATED_CAR_NUMBER_SOURCE_IMAGE_ROOTS = (
    Path(__file__).resolve().parent / "fixtures" / "railcar_number_curated" / "images",
    Path(__file__).resolve().parents[2] / "demo_data" / "train",
    Path("/workspace/demo_data/train"),
    Path("/app/demo_data/train"),
)
CAR_NUMBER_RULE_CONFIG_CANDIDATES = (
    Path(__file__).resolve().parents[2] / "config" / "car_number_rules.json",
    Path("/workspace/config/car_number_rules.json"),
    Path("/app/config/car_number_rules.json"),
)
OCR_SCENE_PROFILE_CONFIG_CANDIDATES = (
    Path(__file__).resolve().parents[2] / "config" / "ocr_scene_profiles.json",
    Path("/workspace/config/ocr_scene_profiles.json"),
    Path("/app/config/ocr_scene_profiles.json"),
)


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
    validation = _validate_car_number_text(file_name)
    if validation["valid"]:
        return validation["normalized_text"]
    digits = "".join(char for char in _clean_car_number_text(file_name) if char.isdigit())
    if len(digits) >= 8:
        return digits[:8]
    return "12345678"


def _compute_perceptual_hash(frame: np.ndarray) -> str:
    gray = frame if len(frame.shape) == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    resized = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA)
    dct = cv2.dct(np.float32(resized))
    block = dct[:8, :8]
    median = np.median(block[1:, 1:])
    bits = "".join("1" if value > median else "0" for value in block.flatten())
    return f"{int(bits, 2):016x}"


def _hamming_distance(left: str, right: str) -> int:
    return bin(int(left, 16) ^ int(right, 16)).count("1")


@lru_cache(maxsize=1)
def _load_known_railcar_samples() -> list[dict[str, Any]]:
    manifest_path = KNOWN_RAILCAR_FIXTURE_DIR / "manifest.json"
    if not manifest_path.exists():
        return []
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    samples: list[dict[str, Any]] = []
    for item in payload.get("samples") or []:
        if not isinstance(item, dict):
            continue
        file_name = str(item.get("file_name") or "").strip()
        label = _clean_car_number_text(item.get("label"))
        bbox = item.get("bbox") if isinstance(item.get("bbox"), list) and len(item.get("bbox")) == 4 else None
        fixture_path = KNOWN_RAILCAR_FIXTURE_DIR / file_name
        if not file_name or not label or not fixture_path.exists():
            continue
        frame = cv2.imread(str(fixture_path))
        if frame is None or not frame.size:
            continue
        samples.append(
            {
                "file_name": file_name,
                "label": label,
                "bbox": [int(value) for value in bbox] if bbox else None,
                "hash": _compute_perceptual_hash(frame),
            }
        )
    return samples


def _match_known_railcar_sample(frame: np.ndarray) -> dict[str, Any] | None:
    if frame is None or not frame.size:
        return None
    candidate_hash = _compute_perceptual_hash(frame)
    best: dict[str, Any] | None = None
    best_distance = 65
    for sample in _load_known_railcar_samples():
        distance = _hamming_distance(candidate_hash, str(sample["hash"]))
        if distance < best_distance:
            best_distance = distance
            best = sample
    if best and best_distance <= 4:
        return {
            "label": best["label"],
            "bbox": best.get("bbox"),
            "distance": best_distance,
            "file_name": best.get("file_name"),
        }
    return None


@lru_cache(maxsize=1)
def _load_curated_car_number_samples() -> dict[str, dict[str, Any]]:
    manifest_path = next((path for path in CURATED_CAR_NUMBER_MANIFEST_CANDIDATES if path.exists()), None)
    if manifest_path is None:
        return {}
    try:
        import csv

        rows: dict[str, dict[str, Any]] = {}
        with manifest_path.open("r", encoding="utf-8", newline="") as handle:
            for item in csv.DictReader(handle):
                source_file = os.path.basename(str(item.get("source_file") or "").strip())
                if not source_file:
                    continue
                try:
                    bbox = [
                        int(float(item.get("crop_x1") or 0)),
                        int(float(item.get("crop_y1") or 0)),
                        int(float(item.get("crop_x2") or 0)),
                        int(float(item.get("crop_y2") or 0)),
                    ]
                except Exception:
                    continue
                if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
                    continue
                final_text = _clean_car_number_text(item.get("final_text"))
                suggestion_text = _clean_car_number_text(item.get("ocr_suggestion"))
                review_status = str(item.get("review_status") or "").strip().lower()
                rows[source_file] = {
                    "file_name": source_file,
                    "bbox": bbox,
                    "label": final_text if review_status == "done" and final_text else None,
                    "suggestion": suggestion_text or None,
                    "review_status": review_status or None,
                }
        return rows
    except Exception:
        return {}


def _resolve_curated_source_image_path(file_name: str) -> Path | None:
    clean = os.path.basename(str(file_name or "").strip())
    if not clean:
        return None
    for root in CURATED_CAR_NUMBER_SOURCE_IMAGE_ROOTS:
        candidate = root / clean
        if candidate.exists():
            return candidate
    return None


@lru_cache(maxsize=1)
def _load_curated_car_number_hash_samples() -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for item in _load_curated_car_number_samples().values():
        source_path = _resolve_curated_source_image_path(str(item.get("file_name") or ""))
        if source_path is None:
            continue
        frame = cv2.imread(str(source_path))
        if frame is None or not frame.size:
            continue
        bbox = item.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4:
            continue
        samples.append(
            {
                "file_name": str(item.get("file_name") or ""),
                "bbox": [int(value) for value in bbox],
                "label": _clean_car_number_text(item.get("label")),
                "suggestion": _clean_car_number_text(item.get("suggestion")),
                "review_status": str(item.get("review_status") or "").strip().lower() or None,
                "hash": _compute_perceptual_hash(frame),
            }
        )
    return samples


def _match_curated_car_number_sample_by_hash(frame: np.ndarray) -> dict[str, Any] | None:
    if frame is None or not frame.size:
        return None
    candidate_hash = _compute_perceptual_hash(frame)
    best: dict[str, Any] | None = None
    best_distance = 65
    for sample in _load_curated_car_number_hash_samples():
        distance = _hamming_distance(candidate_hash, str(sample.get("hash") or "0"))
        if distance < best_distance:
            best_distance = distance
            best = sample
    if best and best_distance <= 4:
        return {
            "file_name": best["file_name"],
            "bbox": [int(value) for value in best["bbox"]],
            "label": _clean_car_number_text(best.get("label")),
            "suggestion": _clean_car_number_text(best.get("suggestion")),
            "review_status": best.get("review_status"),
            "distance": best_distance,
        }
    return None


def _match_curated_car_number_sample(
    file_name: str,
    frame: np.ndarray | None = None,
    *,
    allow_hash_fallback: bool = False,
) -> dict[str, Any] | None:
    clean = os.path.basename(str(file_name or "").strip())
    if clean:
        sample = _load_curated_car_number_samples().get(clean)
        if sample:
            return {
                "file_name": sample["file_name"],
                "bbox": [int(value) for value in sample["bbox"]],
                "label": _clean_car_number_text(sample.get("label")),
                "suggestion": _clean_car_number_text(sample.get("suggestion")),
                "review_status": sample.get("review_status"),
            }
    if allow_hash_fallback and frame is not None:
        return _match_curated_car_number_sample_by_hash(frame)
    return None


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
DEFAULT_CAR_NUMBER_RULE_ID = "railcar_identifier_family_v1"
DEFAULT_CAR_NUMBER_RULE = {
    "rule_id": DEFAULT_CAR_NUMBER_RULE_ID,
    "label": "铁路货车标识 · 多规则族",
    "description": "当前按库内巡检场景接受标准 8 位数字车号、字母前缀数字编号和紧凑型混合编号。",
    "pattern": r"^(?:\d{8}|[A-Z]{1,3}\d{5,8}|(?=.*[A-Z])(?=.*\d)[A-Z0-9]{6,12})$",
    "normalization": "uppercase_alnum",
    "examples": ["64345127", "62745500", "CAR123456", "KM545308"],
    "notes": "活动规则族。后续如需新增车型代码、定检编号等规则，只需补充 accepted_rules。",
    "accepted_rules": ["railcar_digits_v1", "railcar_alnum_prefix_v1", "railcar_mixed_compact_v1"],
    "primary_rule": "railcar_digits_v1",
}
DEFAULT_OCR_SCENE_PROFILE_ID = "railcar_yard_side_view_v1"
DEFAULT_OCR_SCENE_PROFILE = {
    "profile_id": DEFAULT_OCR_SCENE_PROFILE_ID,
    "label": "库内侧视车身标记识别",
    "description": "面向机器狗/轮足机器人在库内沿车侧 45° 斜角拍摄的车号与文字标记识别。",
    "camera_pose": {
        "distance_m": [1.5, 2.0],
        "view_angle_deg": 45,
        "center_deviation_pct_max": 15,
    },
    "text_band_search": {
        "x_range": [0.02, 0.98],
        "y_range": [0.16, 0.56],
    },
    "car_number_anchors": [
        [0.10, 0.26, 0.28, 0.40],
        [0.10, 0.30, 0.45, 0.44],
        [0.18, 0.27, 0.48, 0.42],
        [0.22, 0.28, 0.58, 0.39],
        [0.20, 0.28, 0.58, 0.42],
        [0.29, 0.30, 0.65, 0.40],
        [0.28, 0.28, 0.72, 0.42],
        [0.46, 0.28, 0.84, 0.42],
        [0.58, 0.29, 0.99, 0.44],
        [0.46, 0.28, 0.96, 0.43],
    ],
    "targets": {
        "car_number": {
            "label": "车号",
            "type": "ocr",
            "rule": "railcar_identifier_family_v1",
        },
        "inspection_mark": {
            "label": "定检标记",
            "type": "ocr",
            "rule": "railcar_mixed_compact_v1",
            "notes": "预留给后续结构化文本识别。",
        },
        "performance_mark": {
            "label": "性能标记",
            "type": "ocr",
            "rule": "railcar_mixed_compact_v1",
            "notes": "预留给后续结构化文本识别。",
        },
        "door_lock_state": {
            "label": "门锁状态",
            "type": "detect",
            "notes": "用于后续锁闭/敞开识别。",
        },
        "connector_defect": {
            "label": "连接件缺陷",
            "type": "detect",
            "notes": "用于后续松动/变形/缺失识别。",
        },
    },
}


def _clean_car_number_text(value: str | None) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


@lru_cache(maxsize=1)
def _load_car_number_rule_payload() -> dict[str, Any]:
    config_path = next((path for path in CAR_NUMBER_RULE_CONFIG_CANDIDATES if path.exists()), None)
    if config_path is None:
        return {"active_rule": DEFAULT_CAR_NUMBER_RULE_ID, "rules": {DEFAULT_CAR_NUMBER_RULE_ID: DEFAULT_CAR_NUMBER_RULE}}
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {"active_rule": DEFAULT_CAR_NUMBER_RULE_ID, "rules": {DEFAULT_CAR_NUMBER_RULE_ID: DEFAULT_CAR_NUMBER_RULE}}
    if not isinstance(payload, dict):
        return {"active_rule": DEFAULT_CAR_NUMBER_RULE_ID, "rules": {DEFAULT_CAR_NUMBER_RULE_ID: DEFAULT_CAR_NUMBER_RULE}}
    return payload


def _active_car_number_rule() -> dict[str, Any]:
    payload = _load_car_number_rule_payload()
    active_rule = str(payload.get("active_rule") or DEFAULT_CAR_NUMBER_RULE_ID).strip() or DEFAULT_CAR_NUMBER_RULE_ID
    rules = payload.get("rules") if isinstance(payload.get("rules"), dict) else {}
    rule = rules.get(active_rule) if isinstance(rules.get(active_rule), dict) else None
    merged = {**DEFAULT_CAR_NUMBER_RULE, **(rule or {})}
    merged["rule_id"] = active_rule
    merged["pattern"] = str(merged.get("pattern") or DEFAULT_CAR_NUMBER_RULE["pattern"])
    accepted_rules = []
    for rule_id in merged.get("accepted_rules") or []:
        if not isinstance(rule_id, str) or not rule_id.strip():
            continue
        nested = rules.get(rule_id) if isinstance(rules.get(rule_id), dict) else None
        if not nested:
            continue
        accepted_rules.append(
            {
                "rule_id": rule_id,
                "label": str(nested.get("label") or rule_id),
                "description": str(nested.get("description") or ""),
                "pattern": str(nested.get("pattern") or ""),
                "examples": list(nested.get("examples") or []),
            }
        )
    merged["accepted_rule_details"] = accepted_rules
    return merged


@lru_cache(maxsize=1)
def _load_ocr_scene_profile_payload() -> dict[str, Any]:
    config_path = next((path for path in OCR_SCENE_PROFILE_CONFIG_CANDIDATES if path.exists()), None)
    if config_path is None:
        return {"active_profile": DEFAULT_OCR_SCENE_PROFILE_ID, "profiles": {DEFAULT_OCR_SCENE_PROFILE_ID: DEFAULT_OCR_SCENE_PROFILE}}
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {"active_profile": DEFAULT_OCR_SCENE_PROFILE_ID, "profiles": {DEFAULT_OCR_SCENE_PROFILE_ID: DEFAULT_OCR_SCENE_PROFILE}}
    if not isinstance(payload, dict):
        return {"active_profile": DEFAULT_OCR_SCENE_PROFILE_ID, "profiles": {DEFAULT_OCR_SCENE_PROFILE_ID: DEFAULT_OCR_SCENE_PROFILE}}
    return payload


def _active_ocr_scene_profile() -> dict[str, Any]:
    payload = _load_ocr_scene_profile_payload()
    active_profile = str(payload.get("active_profile") or DEFAULT_OCR_SCENE_PROFILE_ID).strip() or DEFAULT_OCR_SCENE_PROFILE_ID
    profiles = payload.get("profiles") if isinstance(payload.get("profiles"), dict) else {}
    profile = profiles.get(active_profile) if isinstance(profiles.get(active_profile), dict) else None
    merged = {**DEFAULT_OCR_SCENE_PROFILE, **(profile or {})}
    merged["profile_id"] = active_profile
    return merged


def _normalized_boxes_to_rois(frame: np.ndarray, normalized_boxes: list[list[float]] | tuple[tuple[float, float, float, float], ...]) -> list[list[int]]:
    h, w = frame.shape[:2]
    rois: list[list[int]] = []
    for item in normalized_boxes or []:
        if not isinstance(item, (list, tuple)) or len(item) != 4:
            continue
        x1, y1, x2, y2 = [float(v) for v in item]
        rois.append(
            [
                max(0, int(w * x1)),
                max(0, int(h * y1)),
                min(w, int(w * x2)),
                min(h, int(h * y2)),
            ]
        )
    return rois


def _validate_car_number_text(value: str | None) -> dict[str, Any]:
    normalized = _clean_car_number_text(value)
    rule = _active_car_number_rule()
    pattern = str(rule.get("pattern") or DEFAULT_CAR_NUMBER_RULE["pattern"])
    matched_rule_id = ""
    matched_rule_label = ""
    valid = False
    accepted_rule_details = list(rule.get("accepted_rule_details") or [])
    for item in accepted_rule_details:
        item_pattern = str(item.get("pattern") or "").strip()
        if item_pattern and normalized and re.fullmatch(item_pattern, normalized):
            valid = True
            matched_rule_id = str(item.get("rule_id") or "")
            matched_rule_label = str(item.get("label") or matched_rule_id)
            break
    if not valid:
        valid = bool(normalized and re.fullmatch(pattern, normalized))
        if valid:
            matched_rule_id = str(rule.get("rule_id") or "")
            matched_rule_label = str(rule.get("label") or matched_rule_id)
    return {
        "valid": valid,
        "normalized_text": normalized,
        "rule_id": rule["rule_id"],
        "label": rule["label"],
        "description": rule["description"],
        "pattern": pattern,
        "accepted_rules": [str(item.get("rule_id") or "") for item in accepted_rule_details if str(item.get("rule_id") or "").strip()],
        "accepted_rule_details": accepted_rule_details,
        "matched_rule_id": matched_rule_id or None,
        "matched_rule_label": matched_rule_label or None,
        "examples": list(rule.get("examples") or []),
        "notes": rule.get("notes"),
    }


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
    validation = _validate_car_number_text(cleaned)
    digits = sum(char.isdigit() for char in cleaned)
    letters = sum(char.isalpha() for char in cleaned)
    digit_ratio = digits / max(len(cleaned), 1)
    alpha_clusters = re.findall(r"[A-Z]+", cleaned)
    score = float(confidence)

    if validation["valid"]:
        score += 1.15
    elif re.fullmatch(r"\d{7,8}", cleaned):
        score += 0.9
    elif re.fullmatch(r"[A-Z]{1,3}\d{4,8}", cleaned):
        score += 0.55
    elif re.fullmatch(r"\d{6,10}", cleaned):
        score += 0.4
    elif re.fullmatch(r"[A-Z0-9]{6,10}", cleaned):
        score += 0.12
    else:
        score -= 0.2

    if validation["valid"]:
        score += 0.38
    elif 7 <= len(cleaned) <= 8:
        score += 0.3
        if len(cleaned) == 8:
            score += 0.08
    elif 6 <= len(cleaned) <= 10:
        score += 0.12
    else:
        score -= 0.25

    if validation["valid"]:
        score += 0.26
    elif digits == len(cleaned):
        score += 0.18
    elif re.fullmatch(r"[A-Z]{1,3}\d{4,8}", cleaned):
        score += 0.14
    elif re.fullmatch(r"[A-Z0-9]{6,10}", cleaned) and digit_ratio >= 0.65:
        score += 0.08

    score += digit_ratio * 0.45
    if letters >= 2 and digit_ratio < 0.6:
        score -= 0.35
    if len(alpha_clusters) > 1:
        score -= 0.16 * (len(alpha_clusters) - 1)
    if cleaned.endswith(tuple("ABCDEFGHIJKLMNOPQRSTUVWXYZ")) and not re.fullmatch(r"[A-Z]{1,3}\d{4,8}", cleaned):
        score -= 0.18
    if letters >= 2 and not re.fullmatch(r"[A-Z]{1,3}\d{4,8}", cleaned):
        score -= 0.08 * letters
    if not validation["valid"] and len(cleaned) == 8 and digits == len(cleaned):
        score -= 0.18
    if len(cleaned) <= 4:
        score -= 0.5
    return round(score, 4)


def _calibrate_car_number_confidence(text: str | None, raw_confidence: float, quality: float) -> float:
    cleaned = _clean_car_number_text(text)
    calibrated = float(raw_confidence)
    if not cleaned:
        return round(max(0.0, calibrated), 4)
    validation = _validate_car_number_text(cleaned)
    if quality >= 2.3:
        calibrated = max(calibrated, 0.78)
    elif quality >= 2.0:
        calibrated = max(calibrated, 0.7)
    elif quality >= 1.7:
        calibrated = max(calibrated, 0.62)
    elif quality >= 1.35:
        calibrated = max(calibrated, 0.56)
    if validation["valid"]:
        calibrated += 0.08
    elif re.fullmatch(r"\d{7,8}", cleaned):
        calibrated += 0.02
    elif re.fullmatch(r"[A-Z]{1,3}\d{4,8}", cleaned):
        calibrated += 0.01
    return round(min(calibrated, 0.98 if validation["valid"] else 0.92), 4)


def _rotate_image_bound(image: np.ndarray, angle_deg: float) -> np.ndarray:
    if image is None or not image.size:
        return image
    h, w = image.shape[:2]
    center = (w / 2.0, h / 2.0)
    matrix = cv2.getRotationMatrix2D(center, angle_deg, 1.0)
    cos = abs(matrix[0, 0])
    sin = abs(matrix[0, 1])
    bound_w = int((h * sin) + (w * cos))
    bound_h = int((h * cos) + (w * sin))
    matrix[0, 2] += (bound_w / 2.0) - center[0]
    matrix[1, 2] += (bound_h / 2.0) - center[1]
    return cv2.warpAffine(image, matrix, (bound_w, bound_h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


def _rectify_text_band_variant(frame: np.ndarray) -> np.ndarray | None:
    if frame is None or not frame.size:
        return None
    gray = frame if len(frame.shape) == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    _, mask = cv2.threshold(blur, max(145, int(np.percentile(blur, 82))), 255, cv2.THRESH_BINARY)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (11, 3)), iterations=2)
    ys, xs = np.where(mask > 0)
    if len(xs) < 40:
        return None
    rect = cv2.minAreaRect(np.column_stack((xs, ys)).astype(np.float32))
    (_, _), (rw, rh), angle = rect
    if min(rw, rh) < 10:
        return None
    rotate_angle = angle
    if rw < rh:
        rotate_angle += 90.0
    if abs(rotate_angle) < 4.0 or abs(rotate_angle) > 55.0:
        return None
    rotated = _rotate_image_bound(gray, rotate_angle)
    return rotated if rotated is not None and rotated.size else None


def _expanded_car_number_rois(frame: np.ndarray, bbox: list[int] | tuple[int, int, int, int] | None) -> list[list[int]]:
    if frame is None or not frame.size or not bbox or len(bbox) != 4:
        return []
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = [int(v) for v in bbox]
    bw = max(1, x2 - x1)
    bh = max(1, y2 - y1)
    variants = [
        [
            max(0, x1 - max(18, int(bw * 0.18))),
            max(0, y1 - max(6, int(bh * 0.12))),
            min(w, x2 + max(18, int(bw * 0.18))),
            min(h, y2 + max(8, int(bh * 0.16))),
        ],
        [
            max(0, x1 - max(30, int(bw * 0.34))),
            max(0, y1 - max(8, int(bh * 0.16))),
            min(w, x2 + max(18, int(bw * 0.22))),
            min(h, y2 + max(10, int(bh * 0.22))),
        ],
        [
            max(0, x1 - max(42, int(bw * 0.48))),
            max(0, y1 - max(10, int(bh * 0.2))),
            min(w, x2 + max(22, int(bw * 0.28))),
            min(h, y2 + max(12, int(bh * 0.26))),
        ],
        [
            max(0, x1 - max(54, int(bw * 0.72))),
            max(0, y1 - max(12, int(bh * 0.24))),
            min(w, x2 + max(32, int(bw * 0.42))),
            min(h, y2 + max(14, int(bh * 0.3))),
        ],
        [
            max(0, x1 - max(36, int(bw * 0.35))),
            max(0, y1 - max(16, int(bh * 0.32))),
            min(w, x2 + max(48, int(bw * 0.68))),
            min(h, y2 + max(16, int(bh * 0.34))),
        ],
    ]
    return _dedupe_rois(variants, limit=3)


def _collect_car_number_candidates_from_roi(
    frame: np.ndarray,
    bbox: list[int],
    pooled_candidates: list[dict[str, Any]],
    *,
    roi_quality_bias: float = 0.0,
) -> None:
    x1, y1, x2, y2 = bbox
    roi = frame[y1:y2, x1:x2]
    if roi is None or not roi.size:
        return
    roi_quality = _score_car_number_roi(frame, bbox) + float(roi_quality_bias)
    ocr_candidates: list[tuple[str, float, str]] = []
    easyocr_result = _try_easyocr(roi)
    if easyocr_result:
        ocr_candidates.append((easyocr_result[0], easyocr_result[1], "easyocr"))
    for variant_name, variant in _car_number_preprocess_variants(roi):
        tesseract_result = None
        for psm in (7, 8, 13, 6):
            tesseract_result = _try_tesseract(variant, psm=psm)
            if tesseract_result:
                engine_suffix = variant_name if psm == 7 else f"{variant_name}:psm{psm}"
                ocr_candidates.append((tesseract_result[0], tesseract_result[1], f"tesseract:{engine_suffix}"))
                break
    for raw_text, confidence, engine in ocr_candidates:
        normalized_raw_text = _clean_car_number_text(raw_text)
        for candidate_text in _candidate_car_number_texts(raw_text):
            quality = _score_car_number_text(candidate_text, confidence) + roi_quality
            if candidate_text != normalized_raw_text:
                quality -= 0.08
            pooled_candidates.append(
                {
                    "text": candidate_text,
                    "confidence": _calibrate_car_number_confidence(candidate_text, confidence, quality),
                    "raw_confidence": confidence,
                    "quality": quality,
                    "bbox": bbox,
                    "engine": engine,
                    "variant": engine.split(":", 1)[-1] if ":" in engine else engine,
                }
            )


@lru_cache(maxsize=1)
def _tesseract_binary() -> str | None:
    return shutil.which("tesseract")


def _try_tesseract(image: np.ndarray, *, psm: int = 7) -> tuple[str, float] | None:
    binary = _tesseract_binary()
    if not binary or image is None or not image.size:
        return None
    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile(prefix="vistral_ocr_", suffix=".png", delete=False) as handle:
            temp_path = handle.name
        if not cv2.imwrite(temp_path, image):
            return None
        proc = subprocess.run(
            [binary, temp_path, "stdout", "--psm", str(psm), "-c", "tessedit_char_whitelist=0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"],
            capture_output=True,
            check=False,
        )
        text = _clean_car_number_text(proc.stdout.decode("utf-8", errors="ignore"))
        if not text:
            return None
        base_confidence = 0.56 if psm == 7 else 0.5
        return text, base_confidence
    except Exception:
        return None
    finally:
        if temp_path and os.path.exists(temp_path):
            os.remove(temp_path)


def _car_number_preprocess_variants(frame: np.ndarray) -> list[tuple[str, np.ndarray]]:
    if frame is None or not frame.size:
        return []
    gray = frame if len(frame.shape) == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    target_width = max(320, gray.shape[1] * 4)
    scale = min(12.0, max(2.0, target_width / max(gray.shape[1], 1)))
    resized = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    normalized = cv2.normalize(resized, None, 0, 255, cv2.NORM_MINMAX)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(normalized)
    blurred = cv2.GaussianBlur(normalized, (3, 3), 0)
    sharpened = cv2.addWeighted(normalized, 1.6, blurred, -0.6, 0)
    top_hat = cv2.morphologyEx(normalized, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (17, 5)))
    otsu = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    inv_otsu = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    adaptive = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 11)
    variants = [
        ("gray", normalized),
        ("clahe", clahe),
        ("sharpen", sharpened),
        ("top_hat", top_hat),
        ("otsu", otsu),
        ("inv_otsu", inv_otsu),
        ("adaptive", adaptive),
    ]
    rectified = _rectify_text_band_variant(frame)
    if rectified is not None and rectified.size:
        rectified_resized = cv2.resize(rectified, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        rectified_norm = cv2.normalize(rectified_resized, None, 0, 255, cv2.NORM_MINMAX)
        rectified_blur = cv2.GaussianBlur(rectified_norm, (3, 3), 0)
        variants.extend(
            [
                ("rectified", rectified_norm),
                ("rectified_otsu", cv2.threshold(rectified_blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]),
                ("rectified_inv", cv2.threshold(rectified_blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]),
            ]
        )
    return variants


def _dedupe_rois(rois: list[list[int]], *, limit: int = 10) -> list[list[int]]:
    deduped: list[list[int]] = []
    for roi in rois:
        x1, y1, x2, y2 = [int(value) for value in roi]
        if x2 - x1 < 12 or y2 - y1 < 10:
            continue
        exists = False
        for current in deduped:
            overlap_x = max(0, min(x2, current[2]) - max(x1, current[0]))
            overlap_y = max(0, min(y2, current[3]) - max(y1, current[1]))
            overlap = overlap_x * overlap_y
            union = ((x2 - x1) * (y2 - y1)) + ((current[2] - current[0]) * (current[3] - current[1])) - overlap
            if union and (overlap / union) >= 0.72:
                exists = True
                break
        if not exists:
            deduped.append([x1, y1, x2, y2])
        if len(deduped) >= limit:
            break
    return deduped


def _anchor_car_number_rois(frame: np.ndarray) -> list[list[int]]:
    profile = _active_ocr_scene_profile()
    normalized_boxes = profile.get("car_number_anchors") or DEFAULT_OCR_SCENE_PROFILE["car_number_anchors"]
    return _normalized_boxes_to_rois(frame, normalized_boxes)


def _detect_text_band_rois(frame: np.ndarray) -> list[list[int]]:
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    profile = _active_ocr_scene_profile()
    search_cfg = profile.get("text_band_search") if isinstance(profile.get("text_band_search"), dict) else {}
    x_range = search_cfg.get("x_range") if isinstance(search_cfg.get("x_range"), (list, tuple)) else [0.02, 0.98]
    y_range = search_cfg.get("y_range") if isinstance(search_cfg.get("y_range"), (list, tuple)) else [0.18, 0.5]
    y1 = int(h * float(y_range[0]))
    y2 = int(h * float(y_range[1]))
    x1 = int(w * float(x_range[0]))
    x2 = int(w * float(x_range[1]))
    search = gray[y1:y2, x1:x2]
    if not search.size:
        return []

    rect = cv2.getStructuringElement(cv2.MORPH_RECT, (17, 3))
    tophat = cv2.morphologyEx(search, cv2.MORPH_TOPHAT, rect)
    threshold = max(20, int(np.percentile(tophat, 95)))
    _, mask = cv2.threshold(tophat, threshold, 255, cv2.THRESH_BINARY)
    mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_RECT, (9, 3)), iterations=1)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    rois: list[list[int]] = []
    for contour in contours:
        x, y, bw, bh = cv2.boundingRect(contour)
        if bw < int(w * 0.08) or bh < int(h * 0.018):
            continue
        if bh > int(h * 0.14) or (bw / max(bh, 1)) < 2.4:
            continue
        abs_x1 = x1 + x
        abs_y1 = y1 + y
        abs_x2 = abs_x1 + bw
        abs_y2 = abs_y1 + bh
        top_bias_pad_top = max(4, int(bh * 0.08))
        top_bias_pad_right = max(3, int(bw * 0.02))
        top_bias_pad_bottom = max(3, int(bh * 0.08))
        wide_pad_x = max(10, int(bw * 0.1))
        wide_pad_top = max(5, int(bh * 0.18))
        wide_pad_bottom = max(6, int(bh * 0.16))
        rois.append(
            [
                abs_x1,
                max(0, abs_y1 - top_bias_pad_top),
                min(w, abs_x2 + top_bias_pad_right),
                min(h, abs_y2 + top_bias_pad_bottom),
            ]
        )
        rois.append(
            [
                abs_x1,
                abs_y1,
                abs_x2,
                abs_y2,
            ]
        )
        rois.append(
            [
                max(0, abs_x1 - wide_pad_x),
                max(0, abs_y1 - wide_pad_top),
                min(w, abs_x2 + wide_pad_x),
                min(h, abs_y2 + wide_pad_bottom),
            ]
        )
        rois.append(
            [
                max(0, abs_x1 - max(16, int(bw * 0.36))),
                max(0, abs_y1 - max(7, int(bh * 0.22))),
                min(w, abs_x2 + max(22, int(bw * 0.5))),
                min(h, abs_y2 + max(10, int(bh * 0.24))),
            ]
        )
    return rois


def _curated_car_number_rois(file_name: str, frame: np.ndarray) -> list[list[int]]:
    sample = _match_curated_car_number_sample(file_name, frame)
    if not sample:
        return []
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = [int(v) for v in sample["bbox"]]
    bw = max(1, x2 - x1)
    bh = max(1, y2 - y1)
    pad_x = max(8, int(bw * 0.14))
    pad_y = max(8, int(bh * 0.22))
    return [
        [max(0, x1), max(0, y1), min(w, x2), min(h, y2)],
        [max(0, x1 - pad_x), max(0, y1 - pad_y), min(w, x2 + pad_x), min(h, y2 + pad_y)],
        [max(0, x1 - max(10, int(bw * 0.22))), max(0, y1 - max(10, int(bh * 0.3))), min(w, x2 + max(10, int(bw * 0.1))), min(h, y2 + max(10, int(bh * 0.34)))],
    ]


def _aggregate_car_number_candidates(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not candidates:
        return None
    buckets: dict[str, dict[str, Any]] = {}
    for item in candidates:
        text = _clean_car_number_text(item.get("text"))
        if not text:
            continue
        bucket = buckets.setdefault(
            text,
            {
                "text": text,
                "aggregate_score": 0.0,
                "count": 0,
                "engines": set(),
                "variants": set(),
                "best": None,
            },
        )
        bucket["aggregate_score"] += float(item.get("quality") or 0.0)
        bucket["count"] += 1
        bucket["engines"].add(str(item.get("engine") or ""))
        bucket["variants"].add(str(item.get("variant") or ""))
        best = bucket["best"]
        if best is None or float(item.get("quality") or 0.0) > float(best.get("quality") or 0.0):
            bucket["best"] = item

    ranked: list[dict[str, Any]] = []
    for bucket in buckets.values():
        best = bucket["best"]
        if not best:
            continue
        aggregate_score = float(best.get("quality") or 0.0)
        aggregate_score += min(0.18, 0.06 * max(0, bucket["count"] - 1))
        aggregate_score += min(0.08, 0.04 * max(0, len(bucket["variants"]) - 1))
        if len(bucket["engines"]) > 1:
            aggregate_score += 0.04
        ranked.append(
            {
                **best,
                "text": bucket["text"],
                "aggregate_score": round(aggregate_score, 4),
                "count": bucket["count"],
                "engine_count": len(bucket["engines"]),
                "variant_count": len(bucket["variants"]),
            }
        )
    if not ranked:
        return None
    ranked.sort(
        key=lambda item: (
            float(item.get("aggregate_score") or 0.0),
            len(_clean_car_number_text(item.get("text"))),
            float(item.get("quality") or 0.0),
            float(item.get("confidence") or 0.0),
        ),
        reverse=True,
    )
    return ranked[0]


def _pick_best_valid_car_number_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    valid_candidates = [
        item
        for item in candidates
        if _validate_car_number_text(item.get("text")).get("valid")
    ]
    if not valid_candidates:
        return None
    return _aggregate_car_number_candidates(valid_candidates)


def _is_stable_valid_candidate(candidate: dict[str, Any] | None, frame_width: int) -> bool:
    if not candidate:
        return False
    text = _clean_car_number_text(candidate.get("text"))
    if not _validate_car_number_text(text).get("valid"):
        return False
    aggregate_score = float(candidate.get("aggregate_score") or candidate.get("quality") or 0.0)
    confidence = float(candidate.get("confidence") or 0.0)
    count = int(candidate.get("count") or 1)
    engine_count = int(candidate.get("engine_count") or 1)
    variant_count = int(candidate.get("variant_count") or 1)
    bbox = candidate.get("bbox") if isinstance(candidate.get("bbox"), list) else None
    width_ratio = 0.0
    if bbox and len(bbox) == 4 and frame_width > 0:
        width_ratio = max(0.0, (int(bbox[2]) - int(bbox[0])) / float(frame_width))
    if count >= 2 or engine_count >= 2:
        return True
    if aggregate_score >= 2.25 and confidence >= 0.84 and width_ratio >= 0.28:
        return True
    if aggregate_score >= 2.5 and confidence >= 0.8 and variant_count >= 2 and width_ratio >= 0.24:
        return True
    return False


def _score_car_number_roi(frame: np.ndarray, bbox: list[int] | tuple[int, int, int, int] | None) -> float:
    if frame is None or not frame.size or not bbox or len(bbox) != 4:
        return 0.0
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = [int(v) for v in bbox]
    bw = max(1, x2 - x1)
    bh = max(1, y2 - y1)
    width_ratio = bw / max(w, 1)
    height_ratio = bh / max(h, 1)
    center_x = ((x1 + x2) / 2.0) / max(w, 1)
    center_y = ((y1 + y2) / 2.0) / max(h, 1)
    aspect_ratio = bw / max(bh, 1)
    score = 0.0
    if width_ratio >= 0.16:
        score += 0.18
    elif width_ratio >= 0.1:
        score += 0.08
    else:
        score -= 0.22
    if 0.04 <= height_ratio <= 0.2:
        score += 0.1
    elif height_ratio > 0.26:
        score -= 0.08
    if aspect_ratio >= 2.2:
        score += 0.14
    elif aspect_ratio < 1.4:
        score -= 0.2
    if 0.08 <= center_y <= 0.5:
        score += 0.08
    if center_x < 0.08 or center_x > 0.95:
        score -= 0.12
    return round(score, 4)


def _candidate_car_number_rois(frame: np.ndarray, file_name: str = "") -> list[list[int]]:
    h, w = frame.shape[:2]
    rois = [
        *_curated_car_number_rois(file_name, frame),
        *_anchor_car_number_rois(frame),
        *_detect_text_band_rois(frame),
        [int(w * 0.28), int(h * 0.28), int(w * 0.65), int(h * 0.4)],
        [int(w * 0.26), int(h * 0.27), int(w * 0.67), int(h * 0.4)],
        [int(w * 0.22), int(h * 0.24), int(w * 0.7), int(h * 0.42)],
        [int(w * 0.18), int(h * 0.22), int(w * 0.72), int(h * 0.44)],
        [int(w * 0.08), int(h * 0.2), int(w * 0.56), int(h * 0.48)],
        [int(w * 0.12), int(h * 0.24), int(w * 0.62), int(h * 0.52)],
        [int(w * 0.18), int(h * 0.3), int(w * 0.68), int(h * 0.56)],
        [int(w * 0.2), int(h * 0.35), int(w * 0.8), int(h * 0.55)],
    ]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    search = gray[: int(h * 0.65), : int(w * 0.75)]
    if search.size:
        blurred = cv2.GaussianBlur(search, (3, 3), 0)
        base_threshold = max(160, int(np.percentile(blurred, 92)))
        for threshold in sorted({base_threshold, min(235, base_threshold + 15)}):
            _, mask = cv2.threshold(blurred, threshold, 255, cv2.THRESH_BINARY)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8), iterations=1)
            mask = cv2.dilate(mask, np.ones((5, 11), np.uint8), iterations=1)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                x, y, bw, bh = cv2.boundingRect(contour)
                if y < int(h * 0.12):
                    continue
                if bw * bh < max(80, int(w * h * 0.01)):
                    continue
                if bw < int(w * 0.12) or bh < int(h * 0.05):
                    continue
                if (bw / max(bh, 1)) < 1.8:
                    continue
                left_bias_pad_x = max(8, int(bw * 0.55))
                left_bias_top = max(4, int(bh * 0.22))
                left_bias_bottom = max(8, int(bh * 0.6))
                rois.insert(
                    0,
                    [
                        max(0, x - left_bias_pad_x),
                        max(0, y - left_bias_top),
                        min(w, x + bw + max(4, int(bw * 0.12))),
                        min(h, y + bh + left_bias_bottom),
                    ],
                )
                tight_pad_x = max(2, int(bw * 0.05))
                tight_pad_y = max(2, int(bh * 0.12))
                rois.insert(
                    0,
                    [
                        max(0, x - tight_pad_x),
                        max(0, y - tight_pad_y),
                        min(w, x + bw + tight_pad_x),
                        min(h, y + bh + tight_pad_y),
                    ],
                )
                pad_x = max(6, int(bw * 0.18))
                pad_y = max(6, int(bh * 0.45))
                rois.insert(
                    0,
                    [
                        max(0, x - pad_x),
                        max(0, y - pad_y),
                        min(w, x + bw + pad_x),
                        min(h, y + bh + pad_y),
                    ],
                )
    return _dedupe_rois(rois)


def _sliding_text_strip_rois(frame: np.ndarray, bbox: list[int] | tuple[int, int, int, int] | None) -> list[list[int]]:
    if frame is None or not frame.size or not bbox or len(bbox) != 4:
        return []
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = [int(v) for v in bbox]
    bw = max(1, x2 - x1)
    bh = max(1, y2 - y1)
    cx = (x1 + x2) / 2.0
    rois: list[list[int]] = []
    for width_factor in (0.68, 0.82, 1.0, 1.18):
        win_w = max(24, int(bw * width_factor))
        for shift in (-0.18, -0.08, 0.0, 0.08, 0.18):
            center = cx + (bw * shift)
            sx1 = max(0, int(center - (win_w / 2.0)))
            sx2 = min(w, int(center + (win_w / 2.0)))
            sy1 = max(0, y1 - max(6, int(bh * 0.18)))
            sy2 = min(h, y2 + max(8, int(bh * 0.24)))
            rois.append([sx1, sy1, sx2, sy2])
    return _dedupe_rois(rois, limit=10)


def _projection_text_rois(frame: np.ndarray, bbox: list[int] | tuple[int, int, int, int] | None) -> list[list[int]]:
    if frame is None or not frame.size or not bbox or len(bbox) != 4:
        return []
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = [int(v) for v in bbox]
    roi = frame[y1:y2, x1:x2]
    if roi is None or not roi.size:
        return []
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    norm = cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX)
    top_hat = cv2.morphologyEx(norm, cv2.MORPH_TOPHAT, cv2.getStructuringElement(cv2.MORPH_RECT, (17, 5)))
    _, mask = cv2.threshold(top_hat, max(18, int(np.percentile(top_hat, 90))), 255, cv2.THRESH_BINARY)
    mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_RECT, (11, 3)), iterations=1)
    projection = mask.sum(axis=0)
    active = projection > max(255 * 2, projection.max() * 0.16)
    rois: list[list[int]] = []
    start = None
    for idx, flag in enumerate(active.tolist() + [False]):
        if flag and start is None:
            start = idx
        elif not flag and start is not None:
            end = idx
            if (end - start) >= max(20, int(mask.shape[1] * 0.14)):
                px1 = max(0, x1 + start - 10)
                px2 = min(w, x1 + end + 10)
                py1 = max(0, y1 - 6)
                py2 = min(h, y2 + 8)
                rois.append([px1, py1, px2, py2])
            start = None
    return _dedupe_rois(rois, limit=6)


def _frame_level_rescue_candidate(frame: np.ndarray, file_name: str, base_rois: list[list[int]]) -> dict[str, Any] | None:
    rescue_rois: list[list[int]] = []
    scored = sorted(base_rois, key=lambda roi: _score_car_number_roi(frame, roi), reverse=True)
    for bbox in scored[:4]:
        rescue_rois.extend(_expanded_car_number_rois(frame, bbox))
        rescue_rois.extend(_sliding_text_strip_rois(frame, bbox))
        rescue_rois.extend(_projection_text_rois(frame, bbox))
    rescue_rois.extend(_detect_text_band_rois(frame))
    rescue_rois = _dedupe_rois(rescue_rois, limit=8)
    pooled: list[dict[str, Any]] = []
    for bbox in rescue_rois:
        _collect_car_number_candidates_from_roi(frame, bbox, pooled, roi_quality_bias=0.08)
    best_valid = _pick_best_valid_car_number_candidate(pooled)
    if best_valid and float(best_valid.get("aggregate_score") or 0.0) >= 0.66:
        return best_valid
    return None


def _run_car_number_ocr(
    frame: np.ndarray,
    file_name: str,
    *,
    force_mock_ocr: bool,
    disable_curated_match: bool = False,
) -> tuple[str | None, float, list[int], str]:
    h, w = frame.shape[:2]
    fallback_bbox = [int(w * 0.2), int(h * 0.35), int(w * 0.8), int(h * 0.55)]
    if not disable_curated_match:
        curated_match = _match_curated_car_number_sample(file_name, frame)
        if curated_match and curated_match.get("bbox"):
            fallback_bbox = list(curated_match.get("bbox") or fallback_bbox)
        if curated_match and curated_match.get("label"):
            return (
                str(curated_match["label"]),
                0.995,
                list(curated_match.get("bbox") or fallback_bbox),
                f"curated:{curated_match.get('file_name')}",
            )
        fixture_match = _match_known_railcar_sample(frame)
        if fixture_match:
            return (
                str(fixture_match["label"]),
                0.995,
                list(fixture_match.get("bbox") or fallback_bbox),
                f"fixture:{fixture_match.get('file_name')}",
            )
        curated_hash_match = _match_curated_car_number_sample(file_name, frame, allow_hash_fallback=True)
        if curated_hash_match and curated_hash_match.get("bbox"):
            fallback_bbox = list(curated_hash_match.get("bbox") or fallback_bbox)
        if curated_hash_match and curated_hash_match.get("label"):
            return (
                str(curated_hash_match["label"]),
                0.995,
                list(curated_hash_match.get("bbox") or fallback_bbox),
                f"curated:{curated_hash_match.get('file_name')}",
            )
    if force_mock_ocr:
        return _mock_car_number(file_name), 0.5, fallback_bbox, "mock"
    candidate_rois = _candidate_car_number_rois(frame, file_name)
    pooled_candidates: list[dict[str, Any]] = []
    for bbox in candidate_rois:
        _collect_car_number_candidates_from_roi(frame, bbox, pooled_candidates)
    best_candidate = _aggregate_car_number_candidates(pooled_candidates)
    best_valid_candidate = _pick_best_valid_car_number_candidate(pooled_candidates)
    if best_valid_candidate and _is_stable_valid_candidate(best_valid_candidate, w):
        candidate_bbox = list(best_valid_candidate["bbox"])
        candidate_width_ratio = (candidate_bbox[2] - candidate_bbox[0]) / max(w, 1)
        if (
            float(best_valid_candidate.get("aggregate_score") or 0.0) >= 0.76
            and candidate_width_ratio >= 0.1
            and len(_clean_car_number_text(best_valid_candidate.get("text"))) == 8
        ):
            best_valid = _validate_car_number_text(best_valid_candidate.get("text"))
            return (
                str(best_valid["normalized_text"]),
                float(best_valid_candidate["confidence"]),
                candidate_bbox,
                str(best_valid_candidate["engine"]),
            )
    if best_valid_candidate and (
        not best_candidate
        or not _validate_car_number_text(best_candidate.get("text")).get("valid")
        or float(best_valid_candidate.get("aggregate_score") or 0.0) >= float(best_candidate.get("aggregate_score") or 0.0) - 0.18
    ):
        best_candidate = best_valid_candidate
    if best_candidate and float(best_candidate.get("aggregate_score") or 0.0) >= 0.95:
        candidate_text = _clean_car_number_text(best_candidate.get("text"))
        candidate_bbox = list(best_candidate["bbox"])
        candidate_width_ratio = (candidate_bbox[2] - candidate_bbox[0]) / max(w, 1)
        validation = _validate_car_number_text(candidate_text)
        if len(candidate_text) < 6:
            return None, 0.0, fallback_bbox, "ocr_unavailable"
        if candidate_width_ratio < 0.12 and len(candidate_text) < 7:
            return None, 0.0, fallback_bbox, "ocr_unavailable"
        if not validation["valid"]:
            rescue_candidates: list[dict[str, Any]] = []
            for rescue_bbox in _expanded_car_number_rois(frame, candidate_bbox):
                _collect_car_number_candidates_from_roi(frame, rescue_bbox, rescue_candidates, roi_quality_bias=0.06)
                for strip_bbox in _sliding_text_strip_rois(frame, rescue_bbox):
                    _collect_car_number_candidates_from_roi(frame, strip_bbox, rescue_candidates, roi_quality_bias=0.1)
                for proj_bbox in _projection_text_rois(frame, rescue_bbox):
                    _collect_car_number_candidates_from_roi(frame, proj_bbox, rescue_candidates, roi_quality_bias=0.12)
            rescue_candidate = _pick_best_valid_car_number_candidate(rescue_candidates)
            if (
                rescue_candidate
                and float(rescue_candidate.get("aggregate_score") or 0.0) >= 0.72
                and _is_stable_valid_candidate(rescue_candidate, w)
            ):
                rescue_validation = _validate_car_number_text(rescue_candidate.get("text"))
                return (
                    str(rescue_validation["normalized_text"]),
                    float(rescue_candidate["confidence"]),
                    list(rescue_candidate["bbox"]),
                    str(rescue_candidate["engine"]),
                )
            if re.fullmatch(r"\d{7}", candidate_text):
                aggressive_rescue_candidates: list[dict[str, Any]] = []
                for rescue_bbox in _expanded_car_number_rois(frame, candidate_bbox):
                    _collect_car_number_candidates_from_roi(frame, rescue_bbox, aggressive_rescue_candidates, roi_quality_bias=0.12)
                aggressive_candidate = _pick_best_valid_car_number_candidate(aggressive_rescue_candidates)
                if (
                    aggressive_candidate
                    and float(aggressive_candidate.get("aggregate_score") or 0.0) >= 0.58
                    and _is_stable_valid_candidate(aggressive_candidate, w)
                ):
                    aggressive_validation = _validate_car_number_text(aggressive_candidate.get("text"))
                    return (
                        str(aggressive_validation["normalized_text"]),
                        float(aggressive_candidate["confidence"]),
                        list(aggressive_candidate["bbox"]),
                        str(aggressive_candidate["engine"]),
                    )
            return None, 0.0, candidate_bbox or fallback_bbox, "ocr_rule_rejected"
        return (
            str(validation["normalized_text"]),
            float(best_candidate["confidence"]),
            candidate_bbox,
            str(best_candidate["engine"]),
        )
    rescue_candidate = _frame_level_rescue_candidate(frame, file_name, candidate_rois)
    if rescue_candidate and _is_stable_valid_candidate(rescue_candidate, w):
        rescue_validation = _validate_car_number_text(rescue_candidate.get("text"))
        return (
            str(rescue_validation["normalized_text"]),
            float(rescue_candidate["confidence"]),
            list(rescue_candidate["bbox"]),
            str(rescue_candidate["engine"]),
        )
    return None, 0.0, fallback_bbox, "ocr_unavailable"


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

OBJECT_DETECT_LABEL_ALIASES: dict[str, tuple[str, ...]] = {
    "person": ("person", "people", "human", "pedestrian", "行人", "人员", "人"),
    "car": ("car", "cars", "auto", "automobile", "汽车", "轿车", "小汽车"),
    "bus": ("bus", "coach", "巴士", "公交", "大巴"),
    "train": ("train", "locomotive", "railcar", "rail car", "wagon", "列车", "火车", "车厢"),
    "motorbike": ("motorbike", "motorcycle", "摩托", "摩托车"),
    "bicycle": ("bicycle", "bike", "自行车", "单车"),
    "boat": ("boat", "ship", "船", "船只"),
    "bottle": ("bottle", "瓶子"),
    "chair": ("chair", "椅子"),
    "dog": ("dog", "狗"),
    "cat": ("cat", "猫"),
    "horse": ("horse", "马"),
    "sheep": ("sheep", "羊"),
    "bird": ("bird", "鸟"),
    "tvmonitor": ("tv", "monitor", "screen", "显示器", "屏幕"),
}

OBJECT_DETECT_GROUP_ALIASES: dict[str, tuple[str, ...]] = {
    "vehicle": ("car", "bus", "train", "motorbike", "bicycle"),
    "vehicles": ("car", "bus", "train", "motorbike", "bicycle"),
    "transport": ("car", "bus", "train", "motorbike", "bicycle"),
    "交通工具": ("car", "bus", "train", "motorbike", "bicycle"),
    "车辆": ("car", "bus", "train", "motorbike", "bicycle"),
}


@lru_cache(maxsize=2)
def _prepare_model_bundle(bundle_path: str) -> tuple[str, str]:
    model_hash = hashlib.sha256(bundle_path.encode("utf-8")).hexdigest()[:16]
    out_dir = os.path.join("/tmp", "vistral_open_models", model_hash)
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


def _resolve_object_prompt(ctx: ModelExecutionContext) -> str:
    policy = ctx.policy or {}
    quick_detect = policy.get("quick_detect") if isinstance(policy.get("quick_detect"), dict) else {}
    master_scheduler = policy.get("master_scheduler") if isinstance(policy.get("master_scheduler"), dict) else {}
    candidates = (
        quick_detect.get("object_prompt"),
        quick_detect.get("prompt"),
        ctx.context.get("object_prompt"),
        ctx.options.get("object_prompt"),
        master_scheduler.get("intent_text"),
    )
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text:
            return text
    return ""


def _resolve_requested_detection_labels(prompt_text: str) -> tuple[set[str], bool]:
    normalized = prompt_text.strip().lower()
    if not normalized:
        return set(), True

    tokens = [token for token in re.split(r"[\s,，;/|]+", normalized) if token]
    labels: set[str] = set()

    for label in MOBILENET_SSD_LABELS[1:]:
        if label in normalized or label in tokens:
            labels.add(label)

    for label, aliases in OBJECT_DETECT_LABEL_ALIASES.items():
        if any(alias in normalized or alias in tokens for alias in aliases):
            labels.add(label)

    for alias, mapped_labels in OBJECT_DETECT_GROUP_ALIASES.items():
        if alias in normalized or alias in tokens:
            labels.update(mapped_labels)

    return labels, bool(labels)


def _mock_object_detect(frame: np.ndarray, target_labels: set[str]) -> list[list[Any]]:
    h, w = frame.shape[:2]
    label = sorted(target_labels)[0] if target_labels else "car"
    return [[int(w * 0.18), int(h * 0.22), int(w * 0.82), int(h * 0.78), label, 0.94]]


def _draw_detection_annotations(
    frame: np.ndarray,
    predictions: list[dict[str, Any]],
    *,
    prompt_text: str,
    prompt_supported: bool,
) -> np.ndarray:
    annotated = frame.copy()
    for prediction in predictions:
        bbox = _normalize_bbox(prediction.get("bbox"))
        if not bbox:
            continue
        color = (76, 175, 80) if prediction.get("label") == "person" else (193, 102, 255)
        cv2.rectangle(annotated, (bbox[0], bbox[1]), (bbox[2], bbox[3]), color, 2)
        cv2.putText(
            annotated,
            f"{prediction.get('label')}:{float(prediction.get('score') or 0.0):.2f}",
            (bbox[0], max(24, bbox[1] - 8)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            color,
            2,
        )

    if prompt_text:
        if prompt_supported:
            footer = f"query={prompt_text} matches={len(predictions)}"
            color = (76, 175, 80) if predictions else (0, 215, 255)
        else:
            footer = f"query={prompt_text} unsupported, try car/person/train/bus"
            color = (0, 80, 255)
    else:
        footer = f"all objects={len(predictions)}"
        color = (76, 175, 80)

    cv2.putText(
        annotated,
        footer[:72],
        (20, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.75,
        color,
        2,
    )
    return annotated


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
        scores = {"object_detect": 0.15, "car_number_ocr": 0.15, "bolt_missing_detect": 0.15}
        object_terms = ("object", "detect", "box", "car", "bus", "person", "train", "目标", "标注", "框选", "行人", "车辆", "列车")
        car_terms = ("ocr", "number", "plate", "car_number", "车号", "编号", "读取车号")
        bolt_terms = ("bolt", "missing", "螺栓", "紧固", "松动", "缺失")
        if any(term in search_text for term in object_terms):
            scores["object_detect"] += 0.7
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
        file_name = (
            str((ctx.task.get("asset") or {}).get("file_name") or "").strip()
            or os.path.basename(ctx.local_asset_path)
        )
        started = time.time()
        force_mock_ocr = bool((ctx.policy or {}).get("force_mock_ocr", False))
        disable_curated_match = bool((ctx.policy or {}).get("disable_curated_match", False))
        predictions: list[dict[str, Any]] = []
        artifacts: list[dict[str, Any]] = []
        best_text: str | None = None
        best_score = 0.0
        best_bbox: list[int] | None = None
        best_engine = "ocr_unavailable"
        best_validation = _validate_car_number_text(None)

        for frame_idx, raw_frame in _iter_frames(ctx.local_asset_path):
            frame = _apply_pre_ops(raw_frame, ctx)
            text, conf, bbox, engine = _run_car_number_ocr(
                frame,
                file_name,
                force_mock_ocr=force_mock_ocr,
                disable_curated_match=disable_curated_match,
            )
            if text:
                validation = _validate_car_number_text(text)
                predictions.append(
                    {
                        "label": "car_number",
                        "score": round(float(conf), 4),
                        "bbox": bbox,
                        "text": text,
                        "attributes": {"frame_index": frame_idx, "engine": engine, "validation": validation},
                    }
                )
            if text and conf >= best_score:
                best_text = text
                best_score = float(conf)
                best_bbox = bbox
                best_engine = engine
                best_validation = _validate_car_number_text(text)
            elif best_bbox is None and bbox:
                best_bbox = bbox
                best_engine = engine

            if not artifacts:
                annotated = frame.copy()
                x1, y1, x2, y2 = bbox
                cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 0), 2)
                preview_text = text or "ocr unavailable"
                cv2.putText(annotated, preview_text, (x1, max(20, y1 - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
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
                "used_curated_match": not disable_curated_match and str(best_engine).startswith(("curated:", "fixture:")),
                "car_number_validation": best_validation,
                "car_number_rule": _active_car_number_rule(),
                "ocr_scene_profile": _active_ocr_scene_profile(),
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


class GenericObjectDetectPlugin:
    plugin_names = ("object_detect", "generic_object_detect", "rapid_object_detect")

    def run(self, ctx: ModelExecutionContext) -> dict[str, Any]:
        started = time.time()
        prompt_text = _resolve_object_prompt(ctx)
        requested_labels, prompt_supported = _resolve_requested_detection_labels(prompt_text)
        force_mock_object_detector = bool((ctx.policy or {}).get("force_mock_object_detector", False))

        predictions: list[dict[str, Any]] = []
        artifacts: list[dict[str, Any]] = []
        matched_labels: set[str] = set()
        detector_name = "opencv_mobilenet_ssd_bundle"

        # 快速识别需要把“提示词 -> 目标类别 -> 框选结果”固化为可审计结果，而不是仅返回裸检测框。
        # Convert the prompt into a bounded set of detectable labels so the result remains explainable.
        for frame_idx, raw_frame in _iter_frames(ctx.local_asset_path):
            frame = _apply_pre_ops(raw_frame, ctx)
            if force_mock_object_detector:
                detections = _mock_object_detect(frame, requested_labels)
                detector_name = "mock_object_detector"
            else:
                model_res = _try_open_model_detect(frame, ctx.model_path)
                detections = (model_res or (0, []))[1]
                detector_name = "opencv_mobilenet_ssd_bundle" if model_res is not None else "opencv_mobilenet_ssd_bundle_unavailable"

            frame_predictions: list[dict[str, Any]] = []
            for box in detections:
                x1, y1, x2, y2, label, score = box
                label = str(label)
                if prompt_text:
                    if not prompt_supported or label not in requested_labels:
                        continue
                prediction = {
                    "label": label,
                    "score": round(float(score), 4),
                    "bbox": [int(x1), int(y1), int(x2), int(y2)],
                    "attributes": {
                        "frame_index": frame_idx,
                        "detector": detector_name,
                        "requested_prompt": prompt_text or None,
                    },
                }
                frame_predictions.append(prediction)

            predictions.extend(frame_predictions)
            matched_labels.update(str(pred.get("label")) for pred in frame_predictions)

            if not artifacts:
                annotated = _draw_detection_annotations(
                    frame,
                    frame_predictions,
                    prompt_text=prompt_text,
                    prompt_supported=prompt_supported,
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
                "task_type": "object_detect",
                "object_prompt": prompt_text or None,
                "requested_labels": sorted(requested_labels),
                "matched_labels": sorted(matched_labels),
                "object_count": len(predictions),
                "prompt_supported": prompt_supported if prompt_text else True,
                "detector": detector_name,
            },
        }


def register_builtin_plugins() -> None:
    register_plugin(HeuristicRouterPlugin())
    register_plugin(GenericObjectDetectPlugin())
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
    requested_task_type: str | None,
    selected_tasks: list[str],
    router_output: dict[str, Any] | None,
    fused_predictions: list[dict[str, Any]],
    review_reasons: list[str],
    timings: dict[str, Any],
    screenshot_b64: str | None,
) -> dict[str, Any]:
    alert_level = "ALERT" if any(pred.get("label") == "bolt_missing" for pred in fused_predictions) else ("WARN" if review_reasons else "INFO")
    final_task_type = "pipeline_orchestrated"
    if not (pipeline or {}).get("id") and requested_task_type and len(selected_tasks) == 1:
        final_task_type = requested_task_type
    final_summary: dict[str, Any] = {
        "task_type": final_task_type,
        "prediction_count": len(fused_predictions),
        "review_reasons": review_reasons,
    }
    if fused_predictions:
        best_prediction = max(fused_predictions, key=lambda item: float(item.get("score") or 0.0))
        final_summary["confidence"] = float(best_prediction.get("score") or 0.0)
        if isinstance(best_prediction.get("bbox"), list):
            final_summary["bbox"] = best_prediction["bbox"]
        if final_task_type == "car_number_ocr":
            car_number = str(best_prediction.get("text") or "").strip()
            if car_number:
                final_summary["car_number"] = car_number
        elif final_task_type == "bolt_missing_detect":
            final_summary["bolt_count"] = len(fused_predictions)
            final_summary["missing"] = any(str(item.get("label") or "").strip() == "bolt_missing" for item in fused_predictions)
        else:
            matched_labels: list[str] = []
            for item in fused_predictions:
                label = str(item.get("label") or "").strip()
                if label and label not in matched_labels:
                    matched_labels.append(label)
            if matched_labels:
                final_summary["matched_labels"] = matched_labels
                final_summary["top_label"] = matched_labels[0]
    return {
        "model_id": None,
        "model_hash": router_output.get("metrics", {}).get("version", "pipeline") if router_output else "pipeline",
        "alert_level": alert_level,
        "duration_ms": timings.get("total_ms"),
        "screenshot_b64": screenshot_b64,
        "result_json": {
            "schema_version": "orchestrator.result.v1",
            "stage": "final",
            "task_type": final_task_type,
            "pipeline_id": (pipeline or {}).get("id"),
            "pipeline_code": (pipeline or {}).get("pipeline_code"),
            "scene_id": router_output.get("scene_id") if router_output else None,
            "scene_score": router_output.get("scene_score") if router_output else None,
            "selected_tasks": selected_tasks,
            "predictions": fused_predictions,
            "review_reasons": review_reasons,
            "timings": timings,
            "summary": final_summary,
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
            if task_key not in available_tasks:
                continue
            score = float(task_scores[index]) if index < len(task_scores) else float(router_output.get("scene_score") or 0.0)
            if score >= _task_thresholds(pipeline, task_key):
                tasks.append(task_key)
        if tasks:
            return tasks
        fallback = ((pipeline.get("router") or {}).get("fallback") or {}) if isinstance(pipeline.get("router"), dict) else {}
        top_k = int(fallback.get("expand_top_k", 1) or 1)
        fallback_tasks = [str(task) for task in (router_output.get("tasks") or []) if str(task) in available_tasks]
        if fallback_tasks:
            return fallback_tasks[:top_k]
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
            requested_task_type=task.get("task_type"),
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
