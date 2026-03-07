#!/usr/bin/env python3
"""Polling training worker runner for VisionHub training control plane.

This script fills the gap between control-plane APIs and actual worker execution:
- heartbeat + pull jobs
- controlled pull of assets/base model
- local fine-tune command hook (or built-in lightweight trainer)
- package candidate model via model_package_tool
- upload candidate + push terminal status
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import shlex
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Any, Callable

import httpx
from cryptography.fernet import Fernet


class WorkerError(Exception):
    pass


class JobInterrupted(WorkerError):
    def __init__(self, job_id: str, reason: str, status: str):
        self.job_id = job_id
        self.reason = reason
        self.status = status
        super().__init__(f"job {job_id} interrupted: {reason} ({status})")


DATASET_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp"}
DATASET_VIDEO_EXTENSIONS = {".mp4", ".avi", ".mov"}
DATASET_MEDIA_EXTENSIONS = DATASET_IMAGE_EXTENSIONS | DATASET_VIDEO_EXTENSIONS
ARCHIVE_PREVIEW_LIMIT = 20
ARCHIVE_MAX_ENTRIES = 10000
ARCHIVE_MAX_UNCOMPRESSED_BYTES = 1073741824


def _now_ts() -> float:
    return time.time()


def _safe_json_write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _decode_to_file(b64_data: str, target: Path) -> int:
    raw = base64.b64decode(b64_data)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return len(raw)


def _decrypt_base_model(enc_path: Path, out_path: Path, decrypt_key_path: Path, fallback_key_path: Path | None = None) -> None:
    candidates = [decrypt_key_path]
    if fallback_key_path and fallback_key_path not in candidates:
        candidates.append(fallback_key_path)

    payload = enc_path.read_bytes()
    last_error: Exception | None = None
    for candidate in candidates:
        if not candidate.exists():
            continue
        key = candidate.read_bytes().strip()
        try:
            dec = Fernet(key).decrypt(payload)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_bytes(dec)
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            continue
    # Backward compatibility: some historical model.enc payloads are signed-only (not Fernet-encrypted).
    if not payload.startswith(b"gAAAA"):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(payload)
        return
    resolved = [str(path) for path in candidates]
    raise WorkerError(f"failed to decrypt base model with keys: {resolved}") from last_error


def _run_cmd(cmd: str, env: dict[str, str] | None = None) -> None:
    proc = subprocess.run(cmd, shell=True, env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        raise WorkerError(f"command failed({proc.returncode}): {cmd}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")


def _resource_paths_from_row(row: dict[str, Any]) -> list[Path]:
    members = row.get("members")
    if isinstance(members, list) and members:
        paths = [Path(str((item or {}).get("path") or "")) for item in members]
        return [path for path in paths if path.exists() and path.is_file()]
    path = Path(str(row.get("path") or ""))
    if path.exists() and path.is_file():
        return [path]
    return []


def _resource_count_from_rows(rows: list[dict[str, Any]]) -> int:
    return sum(len(_resource_paths_from_row(row)) for row in rows)


def _normalize_archive_member(name: str) -> Path:
    normalized = str(name or "").replace("\\", "/").strip()
    if not normalized:
        raise WorkerError("archive contains empty member name")
    path = Path(normalized)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise WorkerError(f"archive contains unsafe member path: {normalized}")
    return path


def _extract_archive_asset(archive_path: Path, extract_root: Path) -> dict[str, Any]:
    try:
        with zipfile.ZipFile(archive_path) as zf:
            infos = zf.infolist()
            if len(infos) > ARCHIVE_MAX_ENTRIES:
                raise WorkerError(f"archive contains too many entries: {len(infos)} > {ARCHIVE_MAX_ENTRIES}")

            members: list[dict[str, Any]] = []
            total_uncompressed = 0
            ignored_entry_count = 0
            preview_members: list[str] = []
            seen_targets: set[Path] = set()

            # Worker 侧重新校验 ZIP 结构，避免只依赖控制面检查。
            # Re-validate archive structure on worker side instead of trusting control-plane metadata only.
            for info in infos:
                member = _normalize_archive_member(info.filename)
                if info.is_dir() or str(info.filename).endswith("/"):
                    continue

                total_uncompressed += max(info.file_size, 0)
                if total_uncompressed > ARCHIVE_MAX_UNCOMPRESSED_BYTES:
                    raise WorkerError(
                        f"archive exceeds worker extraction limit: {total_uncompressed} > {ARCHIVE_MAX_UNCOMPRESSED_BYTES}"
                    )

                ext = member.suffix.lower()
                if ext not in DATASET_MEDIA_EXTENSIONS:
                    ignored_entry_count += 1
                    continue

                target = extract_root / member
                if target in seen_targets:
                    raise WorkerError(f"archive contains duplicate member path: {member}")
                seen_targets.add(target)
                target.parent.mkdir(parents=True, exist_ok=True)

                with zf.open(info, "r") as src, target.open("wb") as dst:
                    while True:
                        chunk = src.read(1024 * 1024)
                        if not chunk:
                            break
                        dst.write(chunk)

                members.append(
                    {
                        "relative_path": str(member),
                        "path": str(target),
                        "size_bytes": target.stat().st_size,
                    }
                )
                if len(preview_members) < ARCHIVE_PREVIEW_LIMIT:
                    preview_members.append(str(member))

    except zipfile.BadZipFile as exc:
        raise WorkerError(f"invalid ZIP archive: {archive_path}") from exc

    if not members:
        raise WorkerError(f"archive contains no supported image/video resources: {archive_path}")

    return {
        "archive_path": str(archive_path),
        "extracted_dir": str(extract_root),
        "members": members,
        "resource_count": len(members),
        "ignored_entry_count": ignored_entry_count,
        "archive_preview_members": preview_members,
    }


def _mock_train(
    output_model_path: Path,
    train_manifest: Path,
    val_manifest: Path,
    base_model_path: Path | None,
    spec: dict[str, Any],
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    train_rows = json.loads(train_manifest.read_text(encoding="utf-8"))
    val_rows = json.loads(val_manifest.read_text(encoding="utf-8")) if val_manifest.exists() else []
    if progress_callback:
        progress_callback({"stage": "mock_training", "epoch": 0})
    train_resource_count = _resource_count_from_rows(train_rows)
    val_resource_count = _resource_count_from_rows(val_rows)
    payload = {
        "trainer": "mock",
        "epochs": spec.get("epochs", 3),
        "lr": spec.get("learning_rate", 0.0005),
        "train_samples": train_resource_count,
        "val_samples": val_resource_count,
        "base_model": str(base_model_path) if base_model_path else None,
        "generated_at": int(_now_ts()),
    }
    model_bytes = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    output_model_path.parent.mkdir(parents=True, exist_ok=True)
    output_model_path.write_bytes(model_bytes)
    digest = hashlib.sha256(model_bytes).hexdigest()
    return {"final_loss": 0.03, "val_score": 0.91, "artifact_sha256": digest}


def _label_from_row(row: dict[str, Any]) -> str:
    asset = row.get("asset") or {}
    meta = asset.get("meta") if isinstance(asset.get("meta"), dict) else {}
    text = " ".join(
        [
            str(asset.get("file_name") or ""),
            str(meta.get("use_case") or ""),
            str(meta.get("dataset_label") or ""),
            str(meta.get("intended_model_code") or ""),
            str(meta.get("asset_purpose") or ""),
        ]
    ).lower()
    car_keywords = ("car", "number", "ocr", "wagon", "车号", "车厢", "编号")
    bolt_keywords = ("bolt", "missing", "screw", "fastener", "螺栓", "紧固", "松动")
    router_keywords = ("router", "scene_router", "编排", "路由")
    if any(token in text for token in car_keywords):
        return "car_number_ocr"
    if any(token in text for token in bolt_keywords):
        return "bolt_missing_detect"
    if any(token in text for token in router_keywords):
        return "scene_router"
    return "generic_inspection"


def _feature_from_file(path: Path) -> list[float]:
    raw = path.read_bytes()
    total = max(len(raw), 1)
    hist = [0] * 16
    for value in raw:
        hist[value // 16] += 1
    features = [bucket / total for bucket in hist]
    sha = hashlib.sha256(raw).digest()
    features.extend(
        [
            min(total / 200000.0, 1.0),
            sha[0] / 255.0,
            sha[1] / 255.0,
            sha[2] / 255.0,
        ]
    )
    return features


def _dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def _softmax(logits: list[float]) -> list[float]:
    peak = max(logits)
    exp = [math.exp(item - peak) for item in logits]
    denom = sum(exp) or 1.0
    return [item / denom for item in exp]


def _dataset_from_rows(rows: list[dict[str, Any]], labels: list[str], label_to_index: dict[str, int]) -> list[tuple[list[float], int]]:
    data: list[tuple[list[float], int]] = []
    for row in rows:
        label = _label_from_row(row)
        if label not in label_to_index:
            labels.append(label)
            label_to_index[label] = len(labels) - 1
        for path in _resource_paths_from_row(row):
            data.append((_feature_from_file(path), label_to_index[label]))
    return data


def _evaluate(data: list[tuple[list[float], int]], weights: list[list[float]], bias: list[float]) -> tuple[float, float]:
    if not data:
        return 0.0, 0.0
    loss = 0.0
    correct = 0
    for features, target in data:
        logits = [_dot(weight, features) + bias[idx] for idx, weight in enumerate(weights)]
        probs = _softmax(logits)
        pred = max(range(len(probs)), key=lambda idx: probs[idx])
        if pred == target:
            correct += 1
        loss += -math.log(max(probs[target], 1e-12))
    return loss / len(data), correct / len(data)


def _builtin_train(
    output_model_path: Path,
    train_manifest: Path,
    val_manifest: Path,
    base_model_path: Path | None,
    spec: dict[str, Any],
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    train_rows = json.loads(train_manifest.read_text(encoding="utf-8"))
    val_rows = json.loads(val_manifest.read_text(encoding="utf-8")) if val_manifest.exists() else []

    labels: list[str] = []
    label_to_index: dict[str, int] = {}
    train_data = _dataset_from_rows(train_rows, labels, label_to_index)
    val_data = _dataset_from_rows(val_rows, labels, label_to_index)
    if not train_data:
        dim = len(val_data[0][0]) if val_data else 0
        weights = [[0.0 for _ in range(dim)] for _ in range(len(labels))]
        bias = [0.0 for _ in range(len(labels))]
        val_loss, val_acc = _evaluate(val_data, weights, bias) if val_data and labels else (0.0, 0.0)
        payload = {
            "trainer": "builtin_logreg",
            "mode": "no_train_assets",
            "epochs": 0,
            "learning_rate": 0.0,
            "feature_spec": "byte_hist16+sha3+size",
            "labels": labels,
            "weights": weights,
            "bias": bias,
            "base_model": str(base_model_path) if base_model_path else None,
            "train_samples": 0,
            "val_samples": len(val_data),
            "generated_at": int(_now_ts()),
        }
        model_bytes = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        output_model_path.parent.mkdir(parents=True, exist_ok=True)
        output_model_path.write_bytes(model_bytes)
        digest = hashlib.sha256(model_bytes).hexdigest()
        return {
            "trainer": "builtin_logreg",
            "mode": "no_train_assets",
            "epochs": 0,
            "learning_rate": 0.0,
            "train_loss": 0.0,
            "val_loss": round(val_loss, 6),
            "train_accuracy": 0.0,
            "val_accuracy": round(val_acc, 4),
            "final_loss": 0.0,
            "val_score": round(val_acc, 4),
            "artifact_sha256": digest,
            "note": "no readable training assets; placeholder candidate artifact generated",
        }

    dim = len(train_data[0][0])
    class_count = max(len(labels), 1)
    epochs = max(1, int(spec.get("epochs", 6)))
    learning_rate = float(spec.get("learning_rate", 0.25))
    weights = [[0.0 for _ in range(dim)] for _ in range(class_count)]
    bias = [0.0 for _ in range(class_count)]

    final_loss = 0.0
    for _epoch in range(epochs):
        if progress_callback:
            progress_callback({"stage": "training_epoch", "epoch": _epoch + 1, "epochs": epochs})
        for features, target in train_data:
            logits = [_dot(weight, features) + bias[idx] for idx, weight in enumerate(weights)]
            probs = _softmax(logits)
            for cls in range(class_count):
                grad = probs[cls] - (1.0 if cls == target else 0.0)
                if grad == 0.0:
                    continue
                for index in range(dim):
                    weights[cls][index] -= learning_rate * grad * features[index]
                bias[cls] -= learning_rate * grad
        final_loss, _ = _evaluate(train_data, weights, bias)

    train_loss, train_acc = _evaluate(train_data, weights, bias)
    val_loss, val_acc = _evaluate(val_data, weights, bias) if val_data else (train_loss, train_acc)

    payload = {
        "trainer": "builtin_logreg",
        "epochs": epochs,
        "learning_rate": learning_rate,
        "feature_spec": "byte_hist16+sha3+size",
        "labels": labels,
        "weights": weights,
        "bias": bias,
        "base_model": str(base_model_path) if base_model_path else None,
        "train_samples": len(train_data),
        "val_samples": len(val_data),
        "generated_at": int(_now_ts()),
    }
    model_bytes = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    output_model_path.parent.mkdir(parents=True, exist_ok=True)
    output_model_path.write_bytes(model_bytes)
    digest = hashlib.sha256(model_bytes).hexdigest()
    return {
        "trainer": "builtin_logreg",
        "epochs": epochs,
        "learning_rate": round(learning_rate, 6),
        "train_loss": round(train_loss, 6),
        "val_loss": round(val_loss, 6),
        "train_accuracy": round(train_acc, 4),
        "val_accuracy": round(val_acc, 4),
        "final_loss": round(final_loss, 6),
        "val_score": round(val_acc, 4),
        "artifact_sha256": digest,
    }


class TrainingWorkerRunner:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.client = httpx.Client(base_url=args.backend_base_url.rstrip("/"), timeout=60.0, verify=args.verify_tls)
        self.headers = {
            "X-Training-Worker-Code": args.worker_code,
            "X-Training-Worker-Token": args.worker_token,
        }
        self.backend_root = Path(args.backend_root).resolve()
        self.model_decrypt_key_path = Path(args.model_decrypt_key).expanduser().resolve()
        self.model_encrypt_key_path = Path(args.model_encrypt_key).expanduser().resolve()
        self.model_sign_private_key_path = Path(args.model_sign_private_key).expanduser().resolve()

    def close(self) -> None:
        self.client.close()

    def _request_json(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = kwargs.pop("headers", {})
        final_headers = {**self.headers, **headers}
        resp = self.client.request(method, path, headers=final_headers, **kwargs)
        if resp.status_code >= 400:
            raise WorkerError(f"{method} {path} failed ({resp.status_code}): {resp.text}")
        return resp.json()

    def heartbeat(self) -> None:
        self._request_json(
            "POST",
            "/training/workers/heartbeat",
            json={
                "host": self.args.worker_host,
                "status": "ACTIVE",
                "labels": self.args.labels,
                "resources": self.args.resources,
            },
        )

    def pull_jobs(self) -> list[dict[str, Any]]:
        data = self._request_json("POST", "/training/workers/pull-jobs", json={"limit": self.args.pull_limit})
        return data.get("jobs", [])

    def push_update(self, job_id: str, status: str, output_summary: dict[str, Any] | None = None, error_message: str | None = None) -> None:
        self._request_json(
            "POST",
            "/training/workers/push-update",
            json={
                "job_id": job_id,
                "status": status,
                "output_summary": output_summary or {},
                "error_message": error_message,
            },
        )

    def job_control(self, job_id: str) -> dict[str, Any]:
        return self._request_json("GET", f"/training/workers/job-control?job_id={job_id}")

    def ensure_job_active(self, job_id: str, stage: str) -> None:
        control = self.job_control(job_id)
        if control.get("should_stop"):
            raise JobInterrupted(job_id, str(control.get("reason") or stage), str(control.get("status") or "UNKNOWN"))

    def pull_asset(self, job_id: str, asset_id: str, target_file: Path) -> dict[str, Any]:
        data = self._request_json("GET", f"/training/workers/pull-asset?job_id={job_id}&asset_id={asset_id}")
        size = _decode_to_file(data["file_b64"], target_file)
        result = {"asset": data.get("asset", {}), "path": str(target_file), "size_bytes": size}
        asset = result["asset"] if isinstance(result["asset"], dict) else {}
        if asset.get("asset_type") == "archive":
            extract_root = target_file.parent / f"{target_file.stem}_dataset"
            result.update(_extract_archive_asset(target_file, extract_root))
        return result

    def pull_base_model(self, job_id: str, job_dir: Path) -> tuple[Path, dict[str, Any]]:
        data = self._request_json("POST", "/training/workers/pull-base-model", json={"job_id": job_id})
        base = data["base_model"]
        model_dir = job_dir / "base_model"
        manifest_path = model_dir / "manifest.json"
        model_enc_path = model_dir / "model.enc"
        sig_path = model_dir / "signature.sig"
        base_model_path = model_dir / "base_model.bin"

        _decode_to_file(base["manifest_b64"], manifest_path)
        _decode_to_file(base["model_enc_b64"], model_enc_path)
        _decode_to_file(base["signature_b64"], sig_path)
        _decrypt_base_model(
            model_enc_path,
            base_model_path,
            self.model_decrypt_key_path,
            fallback_key_path=self.model_encrypt_key_path,
        )

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        return base_model_path, manifest

    def package_candidate(self, model_path: Path, job: dict[str, Any], out_zip: Path) -> None:
        cmd = [
            sys.executable,
            "-m",
            "app.services.model_package_tool",
            "--model-path",
            str(model_path),
            "--model-id",
            str(job["target_model_code"]),
            "--version",
            str(job["target_version"]),
            "--encrypt-key",
            str(self.model_encrypt_key_path),
            "--signing-private-key",
            str(self.model_sign_private_key_path),
            "--output",
            str(out_zip),
            "--task-type",
            str(job["target_model_code"]),
            "--model-type",
            str(self.args.model_type),
            "--runtime",
            str(self.args.runtime),
            "--plugin-name",
            str(self.args.plugin_name or job["target_model_code"]),
        ]
        env = os.environ.copy()
        env["PYTHONPATH"] = f"{self.backend_root}:{env.get('PYTHONPATH', '')}".rstrip(":")
        proc = subprocess.run(cmd, cwd=str(self.backend_root), capture_output=True, text=True, env=env)
        if proc.returncode != 0:
            raise WorkerError(f"package build failed: {' '.join(shlex.quote(x) for x in cmd)}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")

    def upload_candidate(self, job_id: str, zip_path: Path) -> dict[str, Any]:
        with zip_path.open("rb") as fh:
            files = {"package": (zip_path.name, fh, "application/zip")}
            data = {
                "job_id": job_id,
                "training_round": self.args.training_round,
                "dataset_label": self.args.dataset_label,
                "training_summary": self.args.training_summary,
                "model_type": self.args.model_type,
                "runtime": self.args.runtime,
                "plugin_name": self.args.plugin_name,
            }
            return self._request_json("POST", "/training/workers/upload-candidate", data=data, files=files)

    def _run_train_command(self, cmd_template: str, context: dict[str, str], job_id: str) -> dict[str, Any]:
        cmd = cmd_template.format(**context)
        proc = subprocess.Popen(cmd, shell=True)
        try:
            while True:
                rc = proc.poll()
                if rc is not None:
                    if rc != 0:
                        raise WorkerError(f"command failed({rc}): {cmd}")
                    break
                self.ensure_job_active(job_id, "external_training")
                time.sleep(max(1, int(self.args.control_poll_seconds)))
        except Exception:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
            raise
        metrics_path = Path(context["metrics_json"])
        if metrics_path.exists():
            return json.loads(metrics_path.read_text(encoding="utf-8"))
        return {"trainer": "external", "note": "metrics file not produced"}

    def process_job(self, job: dict[str, Any]) -> None:
        job_id = job["id"]
        job_dir = Path(self.args.work_dir) / f"job_{job_id}"
        train_dir = job_dir / "train"
        val_dir = job_dir / "val"
        output_model = job_dir / "output" / self.args.output_model_name
        package_zip = job_dir / "output" / "candidate_model_package.zip"
        metrics_json = job_dir / "output" / "metrics.json"
        job_dir.mkdir(parents=True, exist_ok=True)

        self.ensure_job_active(job_id, "start")
        self.push_update(job_id, "RUNNING", {"stage": "assets_sync"})

        train_rows: list[dict[str, Any]] = []
        for idx, asset in enumerate(job.get("assets", []), start=1):
            self.ensure_job_active(job_id, "assets_sync")
            target_file = train_dir / f"train_{idx}_{asset.get('id', 'asset')}_{asset.get('file_name', 'blob.bin')}"
            train_rows.append(self.pull_asset(job_id, asset["id"], target_file))

        val_rows: list[dict[str, Any]] = []
        for idx, asset in enumerate(job.get("validation_assets", []), start=1):
            self.ensure_job_active(job_id, "validation_assets_sync")
            target_file = val_dir / f"val_{idx}_{asset.get('id', 'asset')}_{asset.get('file_name', 'blob.bin')}"
            val_rows.append(self.pull_asset(job_id, asset["id"], target_file))

        train_manifest = job_dir / "train_manifest.json"
        val_manifest = job_dir / "val_manifest.json"
        _safe_json_write(train_manifest, train_rows)
        _safe_json_write(val_manifest, val_rows)

        base_model_path: Path | None = None
        base_manifest: dict[str, Any] = {}
        if job.get("base_model"):
            self.ensure_job_active(job_id, "base_model_sync")
            self.push_update(job_id, "RUNNING", {"stage": "base_model_sync"})
            base_model_path, base_manifest = self.pull_base_model(job_id, job_dir)

        self.ensure_job_active(job_id, "training_prepare")
        self.push_update(job_id, "RUNNING", {"stage": "training"})
        started = _now_ts()
        if self.args.trainer_cmd:
            context = {
                "job_dir": str(job_dir),
                "train_manifest": str(train_manifest),
                "val_manifest": str(val_manifest),
                "base_model_path": str(base_model_path or ""),
                "output_model_path": str(output_model),
                "job_json": str(job_dir / "job.json"),
                "metrics_json": str(metrics_json),
            }
            _safe_json_write(Path(context["job_json"]), job)
            metrics = self._run_train_command(self.args.trainer_cmd, context, job_id)
        else:
            if self.args.trainer_mode == "mock":
                metrics = _mock_train(
                    output_model,
                    train_manifest,
                    val_manifest,
                    base_model_path,
                    job.get("spec") or {},
                    progress_callback=lambda _meta: self.ensure_job_active(job_id, "mock_training"),
                )
            else:
                metrics = _builtin_train(
                    output_model,
                    train_manifest,
                    val_manifest,
                    base_model_path,
                    job.get("spec") or {},
                    progress_callback=lambda _meta: self.ensure_job_active(job_id, "builtin_training"),
                )
            _safe_json_write(metrics_json, metrics)

        self.ensure_job_active(job_id, "package_prepare")
        self.push_update(job_id, "RUNNING", {"stage": "package"})
        self.package_candidate(output_model, job, package_zip)
        self.ensure_job_active(job_id, "candidate_upload")
        candidate = self.upload_candidate(job_id, package_zip)

        elapsed = round(_now_ts() - started, 3)
        self.push_update(
            job_id,
            "SUCCEEDED",
            {
                "stage": "completed",
                "duration_sec": elapsed,
                "train_asset_count": len(train_rows),
                "validation_asset_count": len(val_rows),
                "train_resource_count": _resource_count_from_rows(train_rows),
                "validation_resource_count": _resource_count_from_rows(val_rows),
                "base_model_id": (job.get("base_model") or {}).get("id"),
                "base_model_hash": base_manifest.get("model_hash"),
                "candidate_model_id": ((candidate.get("candidate_model") or {}).get("id")),
                **metrics,
            },
        )

    def run(self) -> None:
        while True:
            self.heartbeat()
            jobs = self.pull_jobs()
            for job in jobs:
                try:
                    self.process_job(job)
                    if self.args.once:
                        return
                except JobInterrupted:
                    if self.args.once:
                        return
                except Exception as exc:  # noqa: BLE001
                    try:
                        self.push_update(job.get("id", ""), "FAILED", {"stage": "failed"}, error_message=str(exc)[:2000])
                    except Exception:  # noqa: BLE001
                        pass
                    if self.args.fail_fast:
                        raise
            if self.args.once:
                return
            time.sleep(self.args.poll_seconds)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run VisionHub training worker execution loop.")
    parser.add_argument("--backend-base-url", default=os.getenv("TRAINING_BACKEND_BASE_URL", "http://localhost:8000"))
    parser.add_argument("--worker-code", default=os.getenv("TRAINING_WORKER_CODE", ""))
    parser.add_argument("--worker-token", default=os.getenv("TRAINING_WORKER_TOKEN", ""))
    parser.add_argument("--worker-host", default=os.getenv("TRAINING_WORKER_HOST", "training-worker-local"))
    parser.add_argument("--backend-root", default=os.getenv("TRAINING_BACKEND_ROOT", "./backend"))
    parser.add_argument("--work-dir", default=os.getenv("TRAINING_WORK_DIR", "/tmp/rv_training_worker"))
    parser.add_argument("--model-decrypt-key", default=os.getenv("MODEL_DECRYPT_KEY", "./edge/keys/model_decrypt.key"))
    parser.add_argument("--model-encrypt-key", default=os.getenv("MODEL_ENCRYPT_KEY", "./docker/keys/model_encrypt.key"))
    parser.add_argument("--model-sign-private-key", default=os.getenv("MODEL_SIGN_PRIVATE_KEY", "./docker/keys/model_sign_private.pem"))
    parser.add_argument("--output-model-name", default=os.getenv("TRAINING_OUTPUT_MODEL", "candidate_model.bin"))
    parser.add_argument("--runtime", default=os.getenv("TRAINING_RUNTIME", "python"))
    parser.add_argument("--model-type", default=os.getenv("TRAINING_MODEL_TYPE", "expert"))
    parser.add_argument("--plugin-name", default=os.getenv("TRAINING_PLUGIN_NAME", ""))
    parser.add_argument("--training-round", default=os.getenv("TRAINING_ROUND", "auto-round-1"))
    parser.add_argument("--dataset-label", default=os.getenv("TRAINING_DATASET_LABEL", "worker-managed-dataset"))
    parser.add_argument("--training-summary", default=os.getenv("TRAINING_SUMMARY", "candidate generated by training_worker_runner"))
    parser.add_argument("--poll-seconds", type=int, default=int(os.getenv("TRAINING_POLL_SECONDS", "10")))
    parser.add_argument("--pull-limit", type=int, default=int(os.getenv("TRAINING_PULL_LIMIT", "1")))
    parser.add_argument("--control-poll-seconds", type=int, default=int(os.getenv("TRAINING_CONTROL_POLL_SECONDS", "2")))
    parser.add_argument("--trainer-cmd", default=os.getenv("TRAINING_TRAINER_CMD", ""))
    parser.add_argument(
        "--trainer-mode",
        default=os.getenv("TRAINING_TRAINER_MODE", "builtin"),
        choices=["builtin", "mock"],
        help="built-in trainer mode when TRAINING_TRAINER_CMD is not set",
    )
    parser.add_argument("--verify-tls", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--labels", type=json.loads, default=os.getenv("TRAINING_WORKER_LABELS", '{"kind":"gpu"}'))
    parser.add_argument("--resources", type=json.loads, default=os.getenv("TRAINING_WORKER_RESOURCES", '{"gpu_mem_mb":4096,"cpu":4}'))

    args = parser.parse_args()
    if not args.worker_code:
        parser.error("--worker-code (or TRAINING_WORKER_CODE) is required")
    if not args.worker_token:
        parser.error("--worker-token (or TRAINING_WORKER_TOKEN) is required")
    return args


def main() -> None:
    args = parse_args()
    runner = TrainingWorkerRunner(args)
    try:
        runner.run()
    finally:
        runner.close()


if __name__ == "__main__":
    main()
