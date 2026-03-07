#!/usr/bin/env python3
"""One-click demo bootstrap for Vistral.

This script will:
1) Generate local certs/keys
2) Start core services (postgres/redis/backend/frontend)
3) Generate demo router/expert model packages
4) Supplier submits models; platform approves and releases
5) Platform registers and releases a demo pipeline
6) Generate demo assets (images + optional video)
7) Buyer uploads assets and creates tasks via pipeline
8) Start edge-agent and wait for task completion
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib import error, request


ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = ROOT / "docker" / "docker-compose.yml"
ENV_FILE = ROOT / "docker" / ".env"
ASSET_GEN_SCRIPT = ROOT / "docker" / "scripts" / "generate_demo_assets.py"
OPEN_MODEL_DOWNLOAD_SCRIPT = ROOT / "docker" / "scripts" / "download_open_model.py"
LOCAL_CAR_NUMBER_DATASET_SCRIPT = ROOT / "docker" / "scripts" / "prepare_local_car_number_dataset.py"
TRAINING_WORKER_SCRIPT = ROOT / "docker" / "scripts" / "training_worker_runner.py"
LOCAL_CAR_NUMBER_SOURCE_DIR = ROOT / "demo_data" / "train"

API_BASE = "http://localhost:8000"
BOOTSTRAP_BUILD = os.getenv("BOOTSTRAP_BUILD", "1") != "0"


def _compose_base_cmd() -> list[str]:
    cmd = ["docker", "compose"]
    if ENV_FILE.exists():
        cmd += ["--env-file", str(ENV_FILE)]
    cmd += ["-f", str(COMPOSE_FILE)]
    return cmd


def run_cmd(cmd: list[str], cwd: Path | None = None) -> None:
    print("[cmd]", " ".join(cmd))
    subprocess.run(cmd, cwd=str(cwd or ROOT), check=True)


def run_cmd_capture(cmd: list[str], cwd: Path | None = None) -> str:
    print("[cmd]", " ".join(cmd))
    completed = subprocess.run(
        cmd,
        cwd=str(cwd or ROOT),
        check=True,
        capture_output=True,
        text=True,
    )
    stdout = completed.stdout.strip()
    if stdout:
        print(stdout)
    if completed.stderr.strip():
        print(completed.stderr.strip())
    return stdout

def http_json(method: str, url: str, payload: dict[str, Any] | None = None, token: str | None = None) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"

    req = request.Request(url=url, method=method, data=data, headers=headers)
    try:
        with request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {url}: {body}") from exc


def _multipart_body(fields: dict[str, str], file_field: str, file_name: str, file_bytes: bytes, content_type: str) -> tuple[bytes, str]:
    boundary = f"----vistraldemo{uuid.uuid4().hex}"
    parts: list[bytes] = []

    for k, v in fields.items():
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode())
        parts.append(v.encode("utf-8"))
        parts.append(b"\r\n")

    parts.append(f"--{boundary}\r\n".encode())
    parts.append(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{file_name}"\r\n'.encode()
    )
    parts.append(f"Content-Type: {content_type}\r\n\r\n".encode())
    parts.append(file_bytes)
    parts.append(b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())

    return b"".join(parts), boundary


def http_upload_file(
    url: str,
    token: str,
    file_field: str,
    file_path: Path,
    extra_fields: dict[str, str] | None = None,
    content_type: str = "application/octet-stream",
) -> dict[str, Any]:
    fields = extra_fields or {}
    body, boundary = _multipart_body(
        fields=fields,
        file_field=file_field,
        file_name=file_path.name,
        file_bytes=file_path.read_bytes(),
        content_type=content_type,
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Accept": "application/json",
    }
    req = request.Request(url=url, method="POST", data=body, headers=headers)
    try:
        with request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        body_txt = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} {url}: {body_txt}") from exc


def wait_backend(timeout_sec: int = 180) -> None:
    print("[info] waiting backend health...")
    deadline = time.time() + timeout_sec
    last_err = None
    while time.time() < deadline:
        try:
            data = http_json("GET", f"{API_BASE}/health")
            if data.get("status") == "ok":
                print("[ok] backend is healthy")
                return
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
        time.sleep(2)
    raise RuntimeError(f"backend health check timeout: {last_err}")


def login(username: str, password: str) -> str:
    data = http_json("POST", f"{API_BASE}/auth/login", {"username": username, "password": password})
    token = data.get("access_token")
    if not token:
        raise RuntimeError(f"login failed for {username}: {data}")
    return token


def generate_demo_model_packages() -> dict[str, Path]:
    print("[info] generating demo model packages...")
    ts = int(time.time())
    versions = {
        "scene_router": f"v1.0.{ts}",
        "object_detect": f"v1.0.{ts}",
        "car_number_ocr": f"v1.0.{ts}",
        "bolt_missing_detect": f"v1.0.{ts}",
    }

    compose = _compose_base_cmd()
    outputs: dict[str, Path] = {}

    # Download open-source pretrained model for detection demo.
    run_cmd(
        [
            sys.executable,
            str(OPEN_MODEL_DOWNLOAD_SCRIPT),
            "--output",
            str(ROOT / "backend" / "app" / "uploads" / "open_models" / "mobilenet_ssd_bundle.zip"),
        ]
    )

    for model_id, version in versions.items():
        if model_id in {"object_detect", "bolt_missing_detect"}:
            model_bin = "/app/app/uploads/open_models/mobilenet_ssd_bundle.zip"
        else:
            model_bin = f"/tmp/{model_id}.bin"
        output_zip = f"/app/app/uploads/{model_id}_model_package.zip"
        prep_cmd = ""
        if model_id not in {"object_detect", "bolt_missing_detect"}:
            prep_cmd = f"echo 'demo-{model_id}-payload' > {model_bin} && "
        cmd = compose + [
            "exec",
            "-T",
            "backend",
            "sh",
            "-lc",
            (
                f"{prep_cmd}"
                f"python -m app.services.model_package_tool "
                f"--model-path {model_bin} "
                f"--model-id {model_id} "
                f"--version {version} "
                f"--task-type {'scene_router' if model_id == 'scene_router' else model_id} "
                f"--model-type {'router' if model_id == 'scene_router' else 'expert'} "
                f"--runtime python "
                f"--plugin-name {'heuristic_router' if model_id == 'scene_router' else model_id} "
                f"--encrypt-key /app/keys/model_encrypt.key "
                f"--signing-private-key /app/keys/model_sign_private.pem "
                f"--output {output_zip}"
            ),
        ]
        run_cmd(cmd)
        host_zip = ROOT / "backend" / "app" / "uploads" / f"{model_id}_model_package.zip"
        if not host_zip.exists():
            raise RuntimeError(f"model package missing: {host_zip}")
        outputs[model_id] = host_zip
        print(f"[ok] model package: {host_zip}")

    return outputs


def register_and_release_models(supplier_token: str, platform_admin_token: str, packages: dict[str, Path]) -> dict[str, str]:
    print("[info] supplier submitting models, platform approving and releasing...")
    model_ids: dict[str, str] = {}

    for model_code, package_path in packages.items():
        extra_fields = {}
        if model_code == "scene_router":
            extra_fields = {"model_type": "router", "runtime": "python", "plugin_name": "heuristic_router"}
        # 1) supplier submit
        reg = http_upload_file(
            url=f"{API_BASE}/models/register",
            token=supplier_token,
            file_field="package",
            file_path=package_path,
            extra_fields=extra_fields,
            content_type="application/zip",
        )
        model_id = reg["id"]
        model_ids[model_code] = model_id
        print(f"[ok] supplier submitted model {model_code}: {model_id}, status={reg.get('status')}")

        # 2) platform approve
        approve = http_json(
            "POST",
            f"{API_BASE}/models/approve",
            {"model_id": model_id},
            token=platform_admin_token,
        )
        print(f"[ok] platform approved model {model_code}: status={approve.get('status')}")

        # 3) platform release
        rel = http_json(
            "POST",
            f"{API_BASE}/models/release",
            {
                "model_id": model_id,
                "target_devices": ["edge-01"],
                "target_buyers": ["buyer-demo-001"],
            },
            token=platform_admin_token,
        )
        print(f"[ok] released model {model_code}: release_id={rel.get('release_id')}")

    return model_ids


def register_and_release_pipeline(platform_admin_token: str, model_ids: dict[str, str]) -> dict[str, Any]:
    version = f"v1.0.{int(time.time())}"
    payload = {
        "pipeline_code": "demo-inspection-pipeline",
        "name": "列车车号与紧固件联合巡检",
        "version": version,
        "router_model_id": model_ids["scene_router"],
        "expert_map": {
            "car_number_ocr": [{"model_id": model_ids["car_number_ocr"], "priority": 1}],
            "bolt_missing_detect": [{"model_id": model_ids["bolt_missing_detect"], "priority": 1}],
        },
        "thresholds": {
            "car_number_ocr": {"min_score": 0.45},
            "bolt_missing_detect": {"min_score": 0.55},
        },
        "fusion_rules": {"strategy": "priority", "max_experts_per_task": 2},
        "config": {
            "pre": {"operations": ["denoise", "exposure_compensation"]},
            "post": {},
            "router": {"fallback": {"mode": "human_review", "expand_top_k": 2, "review_below": 0.55}},
            "human_review": {"enabled": True, "conditions": [{"type": "low_confidence", "below": 0.55}, {"type": "no_prediction"}]},
            "threshold_version": "thresholds-v1",
        },
    }
    pipeline = http_json("POST", f"{API_BASE}/pipelines/register", payload, token=platform_admin_token)
    print(f"[ok] registered pipeline: {pipeline['id']} code={pipeline.get('pipeline_code')} version={pipeline.get('version')}")
    released = http_json(
        "POST",
        f"{API_BASE}/pipelines/release",
        {
            "pipeline_id": pipeline["id"],
            "target_devices": ["edge-01"],
            "target_buyers": ["buyer-demo-001"],
            "traffic_ratio": 100,
            "release_notes": "demo pipeline release",
        },
        token=platform_admin_token,
    )
    print(f"[ok] released pipeline: {released['id']} traffic_ratio={released.get('traffic_ratio')}")
    return released


def generate_demo_assets() -> dict[str, Path]:
    print("[info] generating demo assets...")
    run_cmd([sys.executable, str(ASSET_GEN_SCRIPT), "--output-dir", str(ROOT / "demo_data")])

    assets = {
        "car_image": ROOT / "demo_data" / "CAR123456_demo.png",
        "bolt_image": ROOT / "demo_data" / "BOLT_MISSING_001.png",
        "video": ROOT / "demo_data" / "CAR123456_demo.mp4",
    }

    if not assets["car_image"].exists() or not assets["bolt_image"].exists():
        raise RuntimeError("demo image generation failed")

    print(f"[ok] asset image: {assets['car_image']}")
    print(f"[ok] asset image: {assets['bolt_image']}")
    if assets["video"].exists():
        print(f"[ok] asset video: {assets['video']}")
    else:
        print("[warn] demo video not generated; continuing with image-only demo")

    return assets


def prepare_local_car_number_datasets() -> dict[str, Any] | None:
    annotations_path = LOCAL_CAR_NUMBER_SOURCE_DIR / "_annotations.txt"
    if not LOCAL_CAR_NUMBER_SOURCE_DIR.exists() or not annotations_path.exists():
        print("[info] local car-number dataset not found, skipping local training dataset bootstrap")
        return None

    print("[info] preparing local car-number training bundles from demo_data/train ...")
    stdout = run_cmd_capture(
        [
            sys.executable,
            str(LOCAL_CAR_NUMBER_DATASET_SCRIPT),
            "--source-dir",
            str(LOCAL_CAR_NUMBER_SOURCE_DIR),
            "--output-dir",
            str(ROOT / "demo_data" / "generated_datasets"),
        ]
    )
    summary = json.loads(stdout)
    print(
        "[ok] prepared local car-number bundles: "
        f"selected_images={summary.get('selected_images')} "
        f"train={summary.get('bundles', {}).get('train', {}).get('sample_count')} "
        f"validation={summary.get('bundles', {}).get('validation', {}).get('sample_count')}"
    )
    return summary


def recommend_model_for_task(
    operator_token: str,
    *,
    asset_id: str,
    device_code: str,
    intent_text: str,
    expected_task_type: str,
    expected_model_id: str | None = None,
) -> dict[str, Any]:
    recommendation = http_json(
        "POST",
        f"{API_BASE}/tasks/recommend-model",
        {
            "asset_id": asset_id,
            "task_type": None,
            "device_code": device_code,
            "intent_text": intent_text,
            "limit": 3,
        },
        token=operator_token,
    )

    selected_model = recommendation.get("selected_model") or {}
    if not selected_model:
        raise RuntimeError(f"master scheduler returned no model for asset {asset_id}")
    if recommendation.get("inferred_task_type") != expected_task_type:
        raise RuntimeError(
            f"unexpected inferred task type for asset {asset_id}: "
            f"{recommendation.get('inferred_task_type')} != {expected_task_type}"
        )
    if selected_model.get("task_type") != expected_task_type:
        raise RuntimeError(
            f"unexpected recommended model task type for asset {asset_id}: "
            f"{selected_model.get('task_type')} != {expected_task_type}"
        )
    if expected_model_id and selected_model.get("model_id") != expected_model_id:
        print(
            "[warn] scheduler selected an older or different released model: "
            f"expected {expected_model_id}, got {selected_model.get('model_id')}"
        )

    print(
        "[ok] recommended model: "
        f"asset={asset_id} task_type={recommendation.get('inferred_task_type')} "
        f"model={selected_model.get('model_code')} {selected_model.get('version')} "
        f"confidence={recommendation.get('confidence')}"
    )
    print(f"[ok] recommendation summary: {recommendation.get('summary')}")
    return recommendation


def create_task_via_master_scheduler(
    operator_token: str,
    *,
    asset_id: str,
    device_code: str,
    intent_text: str,
    policy: dict[str, Any],
    expected_task_type: str,
    expected_model_id: str | None = None,
) -> str:
    recommendation = recommend_model_for_task(
        operator_token,
        asset_id=asset_id,
        device_code=device_code,
        intent_text=intent_text,
        expected_task_type=expected_task_type,
        expected_model_id=expected_model_id,
    )
    selected_model = recommendation.get("selected_model") or {}

    created = http_json(
        "POST",
        f"{API_BASE}/tasks/create",
        {
            "model_id": None,
            "asset_id": asset_id,
            "task_type": None,
            "device_code": device_code,
            "policy": policy,
            "use_master_scheduler": True,
            "intent_text": intent_text,
        },
        token=operator_token,
    )

    scheduler = created.get("scheduler") or {}
    if created.get("task_type") != expected_task_type:
        raise RuntimeError(
            f"unexpected created task type for asset {asset_id}: "
            f"{created.get('task_type')} != {expected_task_type}"
        )
    if expected_model_id and created.get("model_id") != expected_model_id:
        print(
            "[warn] created task used a different released model than the latest demo release: "
            f"expected {expected_model_id}, got {created.get('model_id')}"
        )
    if not scheduler.get("enabled"):
        raise RuntimeError(f"master scheduler detail missing on created task {created.get('id')}")
    if scheduler.get("selected_model", {}).get("model_id") != selected_model.get("model_id"):
        raise RuntimeError(
            f"task scheduler selected model mismatch for task {created.get('id')}: "
            f"{scheduler.get('selected_model', {}).get('model_id')} != {selected_model.get('model_id')}"
        )

    print(
        "[ok] created task via master scheduler: "
        f"{created['id']} model={created.get('model_code')} task_type={created.get('task_type')}"
    )
    return created["id"]


def create_task_via_pipeline(
    operator_token: str,
    *,
    pipeline_id: str,
    asset_id: str,
    device_code: str,
    intent_text: str,
    context: dict[str, Any],
    options: dict[str, Any],
    policy: dict[str, Any],
) -> str:
    created = http_json(
        "POST",
        f"{API_BASE}/tasks/create",
        {
            "pipeline_id": pipeline_id,
            "asset_id": asset_id,
            "task_type": None,
            "device_code": device_code,
            "policy": policy,
            "use_master_scheduler": False,
            "intent_text": intent_text,
            "context": context,
            "options": options,
        },
        token=operator_token,
    )
    if created.get("pipeline_id") != pipeline_id:
        raise RuntimeError(f"created task missing pipeline binding: {created}")
    print(
        "[ok] created task via pipeline: "
        f"{created['id']} pipeline={created.get('pipeline_code')} version={created.get('pipeline_version')}"
    )
    return created["id"]


def upload_assets_and_create_tasks(operator_token: str, pipeline: dict[str, Any], model_ids: dict[str, str], assets: dict[str, Path]) -> list[str]:
    print("[info] uploading assets and creating tasks...")

    car_asset = http_upload_file(
        url=f"{API_BASE}/assets/upload",
        token=operator_token,
        file_field="file",
        file_path=assets["car_image"],
        extra_fields={"sensitivity_level": "L2", "source_uri": "demo://generated/car_image", "use_case": "wagon-side-car-number"},
        content_type="image/png",
    )
    print(f"[ok] uploaded car image: {car_asset['id']}")

    bolt_asset = http_upload_file(
        url=f"{API_BASE}/assets/upload",
        token=operator_token,
        file_field="file",
        file_path=assets["bolt_image"],
        extra_fields={"sensitivity_level": "L2", "source_uri": "demo://generated/bolt_image", "use_case": "bogie-bolt-check"},
        content_type="image/png",
    )
    print(f"[ok] uploaded bolt image: {bolt_asset['id']}")

    video_asset_id: str | None = None
    if assets["video"].exists():
        video_asset = http_upload_file(
            url=f"{API_BASE}/assets/upload",
            token=operator_token,
            file_field="file",
            file_path=assets["video"],
            extra_fields={"sensitivity_level": "L2", "source_uri": "demo://generated/video", "use_case": "wagon-side-car-number"},
            content_type="video/mp4",
        )
        video_asset_id = video_asset["id"]
        print(f"[ok] uploaded video: {video_asset_id}")

    policies = {
        "upload_raw_video": False,
        "upload_frames": True,
        "desensitize_frames": False,
        "retention_days": 30,
    }
    options = {"thresholds": {}, "max_experts": 2, "return_intermediate": True}

    task_ids: list[str] = []

    car_task_id = create_task_via_pipeline(
        operator_token,
        pipeline_id=pipeline["id"],
        asset_id=car_asset["id"],
        device_code="edge-01",
        intent_text="请执行车厢侧面车号巡检流水线，优先适配 edge-01。",
        context={"scene_hint": "wagon-side", "device_type": "edge-gpu-box", "camera_id": "cam-yard-01"},
        options=options,
        policy=policies,
    )
    task_ids.append(car_task_id)

    bolt_task_id = create_task_via_pipeline(
        operator_token,
        pipeline_id=pipeline["id"],
        asset_id=bolt_asset["id"],
        device_code="edge-01",
        intent_text="请执行紧固件缺陷巡检流水线，优先适配 edge-01。",
        context={"scene_hint": "bogie-close-up", "device_type": "edge-gpu-box", "camera_id": "cam-bogie-02"},
        options=options,
        policy=policies,
    )
    task_ids.append(bolt_task_id)

    if video_asset_id:
        car_video_task_id = create_task_via_pipeline(
            operator_token,
            pipeline_id=pipeline["id"],
            asset_id=video_asset_id,
            device_code="edge-01",
            intent_text="请执行视频车号巡检流水线，优先适配 edge-01。",
            context={"scene_hint": "wagon-side", "device_type": "edge-gpu-box", "camera_id": "cam-yard-03"},
            options=options,
            policy=policies,
        )
        task_ids.append(car_video_task_id)

    return task_ids


def get_model_detail(operator_token: str, model_id: str) -> dict[str, Any]:
    rows = http_json("GET", f"{API_BASE}/models", token=operator_token)
    for row in rows if isinstance(rows, list) else []:
        if row.get("id") == model_id:
            return row
    raise RuntimeError(f"model not visible to operator: {model_id}")


def upload_local_training_assets(operator_token: str, dataset_summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    print("[info] uploading local car-number training bundles...")
    uploaded: dict[str, dict[str, Any]] = {}
    split_to_purpose = {"train": "training", "validation": "validation"}
    for split, purpose in split_to_purpose.items():
        bundle = (dataset_summary.get("bundles") or {}).get(split) or {}
        bundle_path = Path(bundle.get("zip_path") or "")
        if not bundle_path.exists():
            raise RuntimeError(f"prepared bundle missing for {split}: {bundle_path}")
        uploaded[split] = http_upload_file(
            url=f"{API_BASE}/assets/upload",
            token=operator_token,
            file_field="file",
            file_path=bundle_path,
            extra_fields={
                "sensitivity_level": "L2",
                "source_uri": f"demo://local-car-number/{split}",
                "asset_purpose": purpose,
                "dataset_label": str(bundle.get("dataset_label") or f"local-car-number-{split}"),
                "use_case": "wagon-side-car-number-ocr-training",
                "intended_model_code": "car_number_ocr",
            },
            content_type="application/zip",
        )
        print(
            f"[ok] uploaded local {split} bundle: "
            f"{uploaded[split]['id']} resources={(uploaded[split].get('meta') or {}).get('archive_resource_count')}"
        )
    return uploaded


def register_bootstrap_training_worker(platform_admin_token: str) -> dict[str, Any]:
    worker_code = f"bootstrap-train-worker-{uuid.uuid4().hex[:8]}"
    worker = http_json(
        "POST",
        f"{API_BASE}/training/workers/register",
        {
            "worker_code": worker_code,
            "name": "Bootstrap Local Trainer",
            "host": "bootstrap-local-trainer",
            "status": "ACTIVE",
            "labels": {"source": "bootstrap_demo", "task_type": "car_number_ocr"},
            "resources": {"cpu_cores": 4, "gpu_count": 0, "gpu_mem_mb": 0},
        },
        token=platform_admin_token,
    )
    print(f"[ok] registered bootstrap training worker: {worker['worker_code']}")
    return worker


def create_local_training_job(
    operator_token: str,
    *,
    base_model: dict[str, Any],
    train_asset_id: str,
    validation_asset_id: str,
    worker: dict[str, Any],
) -> dict[str, Any]:
    target_version = f"vlocal.{int(time.time())}"
    job = http_json(
        "POST",
        f"{API_BASE}/training/jobs",
        {
            "asset_ids": [train_asset_id],
            "validation_asset_ids": [validation_asset_id],
            "base_model_id": base_model["id"],
            "owner_tenant_id": base_model.get("owner_tenant_id"),
            "training_kind": "finetune",
            "target_model_code": "car_number_ocr_local_ft",
            "target_version": target_version,
            "worker_selector": {
                "worker_codes": [worker["worker_code"]],
                "hosts": [worker.get("host") or "bootstrap-local-trainer"],
            },
            "spec": {
                "epochs": 3,
                "learning_rate": 0.0005,
                "dataset_source": "demo_data/train",
                "annotation_type": "bbox_number",
            },
        },
        token=operator_token,
    )
    print(f"[ok] created local car-number training job: {job['id']} code={job.get('job_code')}")
    return job


def run_training_worker_once(worker: dict[str, Any]) -> None:
    bootstrap_token = worker.get("bootstrap_token")
    if not bootstrap_token:
        raise RuntimeError("bootstrap training worker token missing")
    work_dir = ROOT / "tmp" / "bootstrap_training_worker"
    work_dir.mkdir(parents=True, exist_ok=True)
    print(f"[info] running bootstrap training worker once for {worker['worker_code']} ...")
    run_cmd(
        [
            sys.executable,
            str(TRAINING_WORKER_SCRIPT),
            "--backend-base-url",
            API_BASE,
            "--worker-code",
            worker["worker_code"],
            "--worker-token",
            bootstrap_token,
            "--worker-host",
            worker.get("host") or "bootstrap-local-trainer",
            "--backend-root",
            str(ROOT / "backend"),
            "--model-encrypt-key",
            str(ROOT / "docker" / "keys" / "model_encrypt.key"),
            "--model-sign-private-key",
            str(ROOT / "docker" / "keys" / "model_sign_private.pem"),
            "--work-dir",
            str(work_dir),
            "--once",
            "--trainer-mode",
            "builtin",
        ]
    )


def wait_training_job_done(operator_token: str, job_id: str, timeout_sec: int = 300) -> dict[str, Any]:
    print(f"[info] waiting training job completion: {job_id}")
    deadline = time.time() + timeout_sec
    latest_status = None
    while time.time() < deadline:
        job = http_json("GET", f"{API_BASE}/training/jobs/{job_id}", token=operator_token)
        latest_status = job.get("status")
        if latest_status in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            print(f"[ok] training job finished: {job_id} status={latest_status}")
            return job
        time.sleep(3)
    raise RuntimeError(f"training job timeout: {job_id}, latest_status={latest_status}")


def verify_pipeline_runs(operator_token: str, task_ids: list[str], pipeline_id: str) -> None:
    print("[info] verifying pipeline results...")
    for task_id in task_ids:
        task = http_json("GET", f"{API_BASE}/tasks/{task_id}", token=operator_token)
        if task.get("pipeline_id") != pipeline_id:
            raise RuntimeError(f"task {task_id} not bound to pipeline {pipeline_id}")
        if not task.get("run"):
            raise RuntimeError(f"task {task_id} missing inference run summary")
        results = http_json("GET", f"{API_BASE}/results?task_id={task_id}", token=operator_token)
        rows = results if isinstance(results, list) else []
        stages = {str((row.get("result_json") or {}).get("stage") or "") for row in rows}
        if "final" not in stages:
            raise RuntimeError(f"task {task_id} missing final fused result stage")
        if not stages.intersection({"router", "expert"}):
            raise RuntimeError(f"task {task_id} missing router/expert result stages")
        print(f"[ok] verified pipeline task {task_id}: stages={sorted(stages)}")


def wait_tasks_done(operator_token: str, task_ids: list[str], timeout_sec: int = 300) -> None:
    print("[info] waiting tasks completion...")
    deadline = time.time() + timeout_sec

    last = {}
    while time.time() < deadline:
        all_done = True
        transient_error = None
        for task_id in task_ids:
            try:
                info = http_json("GET", f"{API_BASE}/tasks/{task_id}", token=operator_token)
            except Exception as exc:  # noqa: BLE001
                transient_error = str(exc)
                all_done = False
                continue
            status = info.get("status")
            last[task_id] = status
            if status not in {"SUCCEEDED", "FAILED"}:
                all_done = False
        if transient_error:
            print(f"[warn] transient API error while polling tasks: {transient_error}")
        if all_done:
            print("[ok] tasks completed")
            for task_id in task_ids:
                print(f"  - {task_id}: {last[task_id]}")
            return
        time.sleep(5)

    raise RuntimeError(f"task completion timeout. latest statuses: {last}")


def main() -> None:
    print("[info] bootstrap demo started")

    # 1) keys/certs
    run_cmd(["bash", str(ROOT / "docker" / "scripts" / "generate_local_materials.sh")])

    # 2) core services
    compose = _compose_base_cmd()
    core_cmd = compose + ["up", "-d"]
    if BOOTSTRAP_BUILD:
        core_cmd.append("--build")
    core_cmd += ["postgres", "redis", "backend", "frontend"]
    run_cmd(core_cmd)

    # 3) backend health
    wait_backend()

    # 4) models + pipeline
    packages = generate_demo_model_packages()
    supplier_token = login("supplier_demo", "supplier123")
    platform_admin_token = login("platform_admin", "platform123")
    model_ids = register_and_release_models(supplier_token, platform_admin_token, packages)
    pipeline = register_and_release_pipeline(platform_admin_token, model_ids)

    # 5) assets
    assets = generate_demo_assets()
    local_dataset_summary = prepare_local_car_number_datasets()
    buyer_operator_token = login("buyer_operator", "buyer123")
    task_ids = upload_assets_and_create_tasks(buyer_operator_token, pipeline, model_ids, assets)

    # 6) edge and execution
    edge_cmd = compose + ["--profile", "edge", "up", "-d", "--no-deps"]
    if BOOTSTRAP_BUILD:
        edge_cmd.append("--build")
    edge_cmd.append("edge-agent")
    run_cmd(edge_cmd)
    wait_backend()
    wait_tasks_done(buyer_operator_token, task_ids)
    verify_pipeline_runs(buyer_operator_token, task_ids, pipeline["id"])

    local_training_job: dict[str, Any] | None = None
    if local_dataset_summary:
        base_model = get_model_detail(buyer_operator_token, model_ids["car_number_ocr"])
        uploaded_bundles = upload_local_training_assets(buyer_operator_token, local_dataset_summary)
        bootstrap_worker = register_bootstrap_training_worker(platform_admin_token)
        local_training_job = create_local_training_job(
            buyer_operator_token,
            base_model=base_model,
            train_asset_id=uploaded_bundles["train"]["id"],
            validation_asset_id=uploaded_bundles["validation"]["id"],
            worker=bootstrap_worker,
        )
        run_training_worker_once(bootstrap_worker)
        local_training_job = wait_training_job_done(buyer_operator_token, local_training_job["id"])

    print("\n[done] demo environment is ready.")
    print("frontend: https://localhost:8443")
    print("login: platform_admin/platform123 or buyer_operator/buyer123 or supplier_demo/supplier123")
    print("task ids:")
    for tid in task_ids:
        print(f"  - {tid}")
    if local_training_job:
        print("training job:")
        print(f"  - {local_training_job['id']} status={local_training_job.get('status')} candidate={((local_training_job.get('candidate_model') or {}).get('model_code') or '-')}")
    print("\nYou can inspect results and audit logs from UI now.")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print(f"[error] command failed: {exc}")
        print(
            "[hint] If image pull fails (auth.docker.io timeout), copy docker/.env.example to docker/.env "
            "and configure mirror images before rerun. If images already exist, retry with BOOTSTRAP_BUILD=0."
        )
        sys.exit(exc.returncode)
    except Exception as exc:  # noqa: BLE001
        print(f"[error] {exc}")
        sys.exit(1)
