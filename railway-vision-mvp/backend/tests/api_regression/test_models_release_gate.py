from __future__ import annotations

import io

from backend.tests.api_regression.helpers import ApiRegressionHelper


class ModelReleaseGateRegressionTest(ApiRegressionHelper):
    def test_model_approval_workbench_prefills_capability_and_suggested_assets(self) -> None:
        base_model = next((row for row in self.buyer_models() if row.get("model_type") == "expert"), None)
        self.assertIsNotNone(base_model, "no buyer-visible expert model found")
        asset = self.upload_asset(
            token=self.buyer_token,
            filename=f"{self.unique_name('api-approve-workbench')}.png",
            content=self.tiny_png_bytes(),
            asset_purpose="validation",
            use_case="railcar-number-validation",
            intended_model_code=base_model["model_code"],
            dataset_label="approval-workbench-demo",
        )
        payload = self.request_json(
            "GET",
            f"/models/{base_model['id']}/approval-workbench",
            token=self.platform_token,
        )
        self.assertEqual(payload["model"]["id"], base_model["id"])
        self.assertTrue(payload["capability"]["summary"])
        self.assertIn("recommended_task_type", payload)
        self.assertIn("recent_validation_counts", payload)
        suggested_ids = [row["id"] for row in payload["suggested_assets"]]
        self.assertIn(asset["id"], suggested_ids)

    def test_model_release_workbench_prefills_scope_candidates(self) -> None:
        base_model = next((row for row in self.buyer_models() if row.get("model_type") == "expert"), None)
        self.assertIsNotNone(base_model, "no buyer-visible expert model found")
        payload = self.request_json(
            "GET",
            f"/models/{base_model['id']}/release-workbench",
            token=self.platform_token,
        )
        self.assertEqual(payload["model"]["id"], base_model["id"])
        self.assertIn("scope_candidates", payload)
        self.assertTrue(payload["scope_candidates"]["devices"])
        self.assertTrue(payload["scope_candidates"]["buyers"])
        self.assertIn("recommended_release", payload)
        self.assertTrue(payload["recommended_release"]["target_devices"])
        self.assertTrue(payload["recommended_release"]["target_buyers"])

    def test_supplier_candidate_requires_validation_gate(self) -> None:
        model_code = self.unique_name("api-supplier-candidate")
        version = "v1.0.0"
        package_bytes = self.model_package_bytes(model_code=model_code, version=version, plugin_name="generic_object_detect", task_type="object_detect")
        created = self.request_json(
            "POST",
            "/models/register",
            token=self.supplier_token,
            files={"package": (f"{model_code}.zip", io.BytesIO(package_bytes), "application/zip")},
            data={
                "model_source_type": "finetuned_candidate",
                "model_type": "expert",
                "plugin_name": "generic_object_detect",
                "training_round": "round-api",
                "dataset_label": "supplier-candidate-no-evidence",
                "training_summary": "candidate uploaded without validation evidence",
            },
        )
        readiness = self.request_json("GET", f"/models/{created['id']}/readiness", token=self.platform_token)
        self.assertEqual(readiness["validation_report"]["decision"], "blocked")
        self.assertFalse(readiness["validation_report"]["can_approve"])
        blocked = self.request_json(
            "POST",
            "/models/approve",
            token=self.platform_token,
            expected_status=409,
            json={
                "model_id": created["id"],
                "validation_asset_ids": [],
                "validation_result": "passed",
                "validation_summary": "should be blocked",
            },
        )
        self.assertIn("validation gate", blocked["detail"])

    def test_training_candidate_can_pass_validation_gate_and_release_readiness(self) -> None:
        train_label = self.unique_name("api-model-gate-train")
        validation_label = self.unique_name("api-model-gate-val")
        train_asset = self.upload_asset(
            token=self.buyer_token,
            filename=f"{train_label}.zip",
            content=self.nested_dataset_zip(train_label, media_count=2),
            asset_purpose="training",
            use_case="railcar-number-training",
            intended_model_code="car_number_ocr",
            dataset_label=train_label,
        )
        validation_asset = self.upload_asset(
            token=self.buyer_token,
            filename=f"{validation_label}.zip",
            content=self.nested_dataset_zip(validation_label, media_count=2),
            asset_purpose="validation",
            use_case="railcar-number-validation",
            intended_model_code="car_number_ocr",
            dataset_label=validation_label,
        )

        base_model = next((row for row in self.buyer_models() if row.get("model_type") == "expert"), None)
        self.assertIsNotNone(base_model, "no buyer-visible expert model found")

        worker_code = self.unique_name("api-model-gate-worker")
        worker_host = f"{worker_code}.local"
        worker = self.request_json(
            "POST",
            "/training/workers/register",
            token=self.platform_token,
            json={
                "worker_code": worker_code,
                "name": "API Model Gate Worker",
                "host": worker_host,
                "status": "ACTIVE",
                "labels": {"kind": "gpu", "suite": "api-model-gate"},
                "resources": {"gpu_mem_mb": 12288, "cpu": 8},
            },
        )
        worker_token = worker["bootstrap_token"]

        model_code = self.unique_name("api-gated-candidate")
        version = "v2.0.0"
        job = self.request_json(
            "POST",
            "/training/jobs",
            token=self.buyer_token,
            json={
                "asset_ids": [train_asset["id"]],
                "validation_asset_ids": [validation_asset["id"]],
                "base_model_id": base_model["id"],
                "owner_tenant_id": base_model.get("owner_tenant_id"),
                "training_kind": "finetune",
                "target_model_code": model_code,
                "target_version": version,
                "worker_selector": {"hosts": [worker_host]},
                "spec": {"epochs": 3, "learning_rate": 0.01},
            },
        )
        self.request_json(
            "POST",
            "/training/workers/heartbeat",
            headers=self.worker_headers(worker_code, worker_token),
            json={
                "host": worker_host,
                "status": "ACTIVE",
                "labels": {"kind": "gpu", "suite": "api-model-gate"},
                "resources": {"gpu_mem_mb": 12288, "cpu": 8},
            },
        )
        pulled = self.request_json(
            "POST",
            "/training/workers/pull-jobs",
            headers=self.worker_headers(worker_code, worker_token),
            json={"limit": 1},
        )
        self.assertTrue(any(row["id"] == job["id"] for row in pulled["jobs"]), pulled)

        self.request_json(
            "POST",
            "/training/workers/push-update",
            headers=self.worker_headers(worker_code, worker_token),
            json={
                "job_id": job["id"],
                "status": "SUCCEEDED",
                "output_summary": {
                    "stage": "completed",
                    "train_samples": 24,
                    "val_samples": 6,
                    "val_score": 0.93,
                    "val_accuracy": 0.91,
                    "val_loss": 0.08,
                    "history_count": 3,
                    "history": [
                        {"epoch": 1, "train_loss": 0.42, "val_loss": 0.21, "train_accuracy": 0.72, "val_accuracy": 0.79},
                        {"epoch": 2, "train_loss": 0.19, "val_loss": 0.11, "train_accuracy": 0.84, "val_accuracy": 0.88},
                        {"epoch": 3, "train_loss": 0.09, "val_loss": 0.08, "train_accuracy": 0.9, "val_accuracy": 0.91},
                    ],
                    "best_checkpoint": {"epoch": 3, "metric": "val_accuracy", "value": 0.91, "path": "checkpoints/best.pt"},
                },
            },
        )

        package_bytes = self.model_package_bytes(
            model_code=model_code,
            version=version,
            plugin_name="car_number_ocr",
            task_type="car_number_ocr",
        )
        uploaded = self.request_json(
            "POST",
            "/training/workers/upload-candidate",
            headers=self.worker_headers(worker_code, worker_token),
            files={"package": (f"{model_code}.zip", io.BytesIO(package_bytes), "application/zip")},
            data={
                "job_id": job["id"],
                "training_round": "round-model-gate",
                "dataset_label": train_label,
                "training_summary": "candidate with full validation evidence",
                "model_type": "expert",
                "runtime": "python",
                "plugin_name": "car_number_ocr",
                "inputs_json": '{"media":["image"]}',
                "outputs_json": '{"predictions":["label","score","bbox","text"]}',
                "gpu_mem_mb": "2048",
                "latency_ms": "45",
            },
        )
        candidate = uploaded["candidate_model"]

        readiness = self.request_json("GET", f"/models/{candidate['id']}/readiness", token=self.platform_token)
        self.assertTrue(readiness["validation_report"]["can_approve"])
        self.assertEqual(readiness["validation_report"]["validation_result"], "passed")
        self.assertEqual(readiness["validation_report"]["metrics"]["history_count"], 3)
        self.assertEqual(readiness["validation_report"]["metrics"]["best_checkpoint"]["path"], "checkpoints/best.pt")
        self.assertFalse(readiness["default_release_risk_summary"]["can_release"])

        blocked_release = self.request_json(
            "POST",
            "/models/release-readiness",
            token=self.platform_token,
            json={
                "model_id": candidate["id"],
                "target_devices": ["edge-01"],
                "target_buyers": ["buyer-demo-001"],
                "delivery_mode": "local_key",
                "authorization_mode": "device_key",
                "runtime_encryption": True,
            },
        )
        self.assertFalse(blocked_release["release_risk_summary"]["can_release"])

        approved = self.request_json(
            "POST",
            "/models/approve",
            token=self.platform_token,
            json={
                "model_id": candidate["id"],
                "validation_asset_ids": [validation_asset["id"]],
                "validation_result": "passed",
                "validation_summary": "auto validation gate passed",
            },
        )
        self.assertEqual(approved["status"], "APPROVED")

        releasable = self.request_json(
            "POST",
            "/models/release-readiness",
            token=self.platform_token,
            json={
                "model_id": candidate["id"],
                "target_devices": ["edge-01"],
                "target_buyers": ["buyer-demo-001"],
                "delivery_mode": "local_key",
                "authorization_mode": "device_key",
                "runtime_encryption": True,
                "local_key_label": "edge/keys/candidate.key",
            },
        )
        self.assertTrue(releasable["release_risk_summary"]["can_release"])

        release = self.request_json(
            "POST",
            "/models/release",
            token=self.platform_token,
            json={
                "model_id": candidate["id"],
                "target_devices": ["edge-01"],
                "target_buyers": ["buyer-demo-001"],
                "delivery_mode": "local_key",
                "authorization_mode": "device_key",
                "runtime_encryption": True,
                "local_key_label": "edge/keys/candidate.key",
            },
        )
        self.assertEqual(release["status"], "RELEASED")
        self.assertTrue(release["release_risk_summary"]["can_release"])
