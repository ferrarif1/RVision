#!/usr/bin/env python3
"""Polling training worker runner for RVision training control plane.

This script fills the gap between control-plane APIs and actual worker execution:
- heartbeat + pull jobs
- controlled pull of assets/base model
- local fine-tune command hook (or built-in mock trainer)
- package candidate model via model_package_tool
- upload candidate + push terminal status
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from cryptography.fernet import Fernet


class WorkerError(Exception):
    pass


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


def _decrypt_base_model(enc_path: Path, out_path: Path, decrypt_key_path: Path) -> None:
    key = decrypt_key_path.read_bytes().strip()
    dec = Fernet(key).decrypt(enc_path.read_bytes())
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(dec)


def _run_cmd(cmd: str, env: dict[str, str] | None = None) -> None:
    proc = subprocess.run(cmd, shell=True, env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        raise WorkerError(f"command failed({proc.returncode}): {cmd}\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")


def _mock_train(output_model_path: Path, train_manifest: Path, val_manifest: Path, base_model_path: Path | None, spec: dict[str, Any]) -> dict[str, Any]:
    train_rows = json.loads(train_manifest.read_text(encoding="utf-8"))
    val_rows = json.loads(val_manifest.read_text(encoding="utf-8")) if val_manifest.exists() else []
    payload = {
        "trainer": "mock",
        "epochs": spec.get("epochs", 3),
        "lr": spec.get("learning_rate", 0.0005),
        "train_samples": len(train_rows),
        "val_samples": len(val_rows),
        "base_model": str(base_model_path) if base_model_path else None,
        "generated_at": int(_now_ts()),
    }
    model_bytes = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    output_model_path.parent.mkdir(parents=True, exist_ok=True)
    output_model_path.write_bytes(model_bytes)
    digest = hashlib.sha256(model_bytes).hexdigest()
    return {"final_loss": 0.03, "val_score": 0.91, "artifact_sha256": digest}


class TrainingWorkerRunner:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.client = httpx.Client(base_url=args.backend_base_url.rstrip("/"), timeout=60.0, verify=args.verify_tls)
        self.headers = {"Authorization": f"Bearer {args.worker_token}"}
        self.backend_root = Path(args.backend_root).resolve()

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

    def pull_asset(self, job_id: str, asset_id: str, target_file: Path) -> dict[str, Any]:
        data = self._request_json("GET", f"/training/workers/pull-asset?job_id={job_id}&asset_id={asset_id}")
        size = _decode_to_file(data["file_b64"], target_file)
        return {"asset": data.get("asset", {}), "path": str(target_file), "size_bytes": size}

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
        _decrypt_base_model(model_enc_path, base_model_path, Path(self.args.model_decrypt_key))

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
            self.args.model_encrypt_key,
            "--signing-private-key",
            self.args.model_sign_private_key,
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

    def _run_train_command(self, cmd_template: str, context: dict[str, str]) -> dict[str, Any]:
        cmd = cmd_template.format(**context)
        _run_cmd(cmd)
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

        self.push_update(job_id, "RUNNING", {"stage": "assets_sync"})

        train_rows: list[dict[str, Any]] = []
        for idx, asset in enumerate(job.get("assets", []), start=1):
            target_file = train_dir / f"train_{idx}_{asset.get('id', 'asset')}_{asset.get('file_name', 'blob.bin')}"
            train_rows.append(self.pull_asset(job_id, asset["id"], target_file))

        val_rows: list[dict[str, Any]] = []
        for idx, asset in enumerate(job.get("validation_assets", []), start=1):
            target_file = val_dir / f"val_{idx}_{asset.get('id', 'asset')}_{asset.get('file_name', 'blob.bin')}"
            val_rows.append(self.pull_asset(job_id, asset["id"], target_file))

        train_manifest = job_dir / "train_manifest.json"
        val_manifest = job_dir / "val_manifest.json"
        _safe_json_write(train_manifest, train_rows)
        _safe_json_write(val_manifest, val_rows)

        base_model_path: Path | None = None
        base_manifest: dict[str, Any] = {}
        if job.get("base_model"):
            self.push_update(job_id, "RUNNING", {"stage": "base_model_sync"})
            base_model_path, base_manifest = self.pull_base_model(job_id, job_dir)

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
            metrics = self._run_train_command(self.args.trainer_cmd, context)
        else:
            metrics = _mock_train(output_model, train_manifest, val_manifest, base_model_path, job.get("spec") or {})
            _safe_json_write(metrics_json, metrics)

        self.push_update(job_id, "RUNNING", {"stage": "package"})
        self.package_candidate(output_model, job, package_zip)
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
    parser = argparse.ArgumentParser(description="Run RVision training worker execution loop.")
    parser.add_argument("--backend-base-url", default=os.getenv("TRAINING_BACKEND_BASE_URL", "http://localhost:8000"))
    parser.add_argument("--worker-token", default=os.getenv("TRAINING_WORKER_TOKEN", ""))
    parser.add_argument("--worker-host", default=os.getenv("TRAINING_WORKER_HOST", "training-worker-local"))
    parser.add_argument("--backend-root", default=os.getenv("TRAINING_BACKEND_ROOT", "./backend"))
    parser.add_argument("--work-dir", default=os.getenv("TRAINING_WORK_DIR", "/tmp/rv_training_worker"))
    parser.add_argument("--model-decrypt-key", default=os.getenv("MODEL_DECRYPT_KEY", "./docker/keys/model_encrypt.key"))
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
    parser.add_argument("--trainer-cmd", default=os.getenv("TRAINING_TRAINER_CMD", ""))
    parser.add_argument("--verify-tls", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--labels", type=json.loads, default=os.getenv("TRAINING_WORKER_LABELS", '{"kind":"gpu"}'))
    parser.add_argument("--resources", type=json.loads, default=os.getenv("TRAINING_WORKER_RESOURCES", '{"gpu_mem_mb":4096,"cpu":4}'))

    args = parser.parse_args()
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
