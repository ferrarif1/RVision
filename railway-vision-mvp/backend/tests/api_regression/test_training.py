from __future__ import annotations

import time

from backend.tests.api_regression.helpers import ApiRegressionHelper


class TrainingRegressionTest(ApiRegressionHelper):
    def test_training_job_worker_control_contract(self) -> None:
        train_label = self.unique_name("api-regression-train")
        validation_label = self.unique_name("api-regression-val")
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

        worker_code = self.unique_name("api-train-worker")
        worker_host = f"{worker_code}.local"
        worker = self.request_json(
            "POST",
            "/training/workers/register",
            token=self.platform_token,
            json={
                "worker_code": worker_code,
                "name": "API Regression Worker",
                "host": worker_host,
                "status": "ACTIVE",
                "labels": {"kind": "gpu", "suite": "api-regression"},
                "resources": {"gpu_mem_mb": 8192, "cpu": 8},
            },
        )
        worker_token = worker["bootstrap_token"]

        visible_workers = self.request_json("GET", "/training/workers", token=self.buyer_token)
        self.assertTrue(any(row["worker_code"] == worker_code for row in visible_workers), visible_workers)

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
                "target_model_code": self.unique_name("api-regression-candidate"),
                "target_version": "v1.0.0",
                "worker_selector": {"hosts": [worker_host], "labels": {"suite": "api-regression"}},
                "spec": {"epochs": 1, "learning_rate": 0.1},
            },
        )
        self.assertEqual(job["asset_count"], 1)
        self.assertEqual(job["validation_asset_count"], 1)
        self.assertTrue(job["can_cancel"])

        job_detail = self.request_json("GET", f"/training/jobs/{job['id']}", token=self.buyer_token)
        self.assertEqual(job_detail["asset_ids"], [train_asset["id"]])
        self.assertEqual(job_detail["validation_asset_ids"], [validation_asset["id"]])

        heartbeat = self.request_json(
            "POST",
            "/training/workers/heartbeat",
            headers=self.worker_headers(worker_code, worker_token),
            json={
                "host": worker_host,
                "status": "ACTIVE",
                "labels": {"kind": "gpu", "suite": "api-regression"},
                "resources": {"gpu_mem_mb": 8192, "cpu": 8},
            },
        )
        self.assertEqual(heartbeat["worker_code"], worker_code)

        pulled = self.request_json(
            "POST",
            "/training/workers/pull-jobs",
            headers=self.worker_headers(worker_code, worker_token),
            json={"limit": 2},
        )
        assigned = next((row for row in pulled["jobs"] if row["id"] == job["id"]), None)
        self.assertIsNotNone(assigned, pulled)
        self.assertEqual(assigned["assigned_worker_code"], worker_code)

        control_before = self.request_json(
            "GET",
            f"/training/workers/job-control?job_id={job['id']}",
            headers=self.worker_headers(worker_code, worker_token),
        )
        self.assertFalse(control_before["should_stop"])

        pulled_train_asset = self.request_json(
            "GET",
            f"/training/workers/pull-asset?job_id={job['id']}&asset_id={train_asset['id']}",
            headers=self.worker_headers(worker_code, worker_token),
        )
        self.assertEqual(pulled_train_asset["asset"]["purpose"], "training")
        self.assertTrue(pulled_train_asset["file_b64"])

        pulled_validation_asset = self.request_json(
            "GET",
            f"/training/workers/pull-asset?job_id={job['id']}&asset_id={validation_asset['id']}",
            headers=self.worker_headers(worker_code, worker_token),
        )
        self.assertEqual(pulled_validation_asset["asset"]["purpose"], "validation")

        pulled_base_model = self.request_json(
            "POST",
            "/training/workers/pull-base-model",
            headers=self.worker_headers(worker_code, worker_token),
            json={"job_id": job["id"]},
        )
        self.assertEqual(pulled_base_model["base_model"]["id"], base_model["id"])
        self.assertTrue(pulled_base_model["base_model"]["manifest_b64"])

        cancelled = self.request_json(
            "POST",
            f"/training/jobs/{job['id']}/cancel",
            token=self.buyer_token,
            json={"note": "cancel from api regression"},
        )
        self.assertEqual(cancelled["status"], "CANCELLED")

        control_after_cancel = self.request_json(
            "GET",
            f"/training/workers/job-control?job_id={job['id']}",
            headers=self.worker_headers(worker_code, worker_token),
        )
        self.assertTrue(control_after_cancel["should_stop"])
        self.assertEqual(control_after_cancel["status"], "CANCELLED")

        retried = self.request_json(
            "POST",
            f"/training/jobs/{job['id']}/retry",
            token=self.buyer_token,
            json={"note": "retry from api regression"},
        )
        self.assertEqual(retried["status"], "PENDING")
        self.assertIsNone(retried["assigned_worker_code"])

        # 改派前刷新一次训练机心跳，避免测试环境中健康巡检把空闲 worker 提前标为异常。
        self.request_json(
            "POST",
            "/training/workers/heartbeat",
            headers=self.worker_headers(worker_code, worker_token),
            json={
                "host": worker_host,
                "status": "ACTIVE",
                "labels": {"kind": "gpu", "suite": "api-regression"},
                "resources": {"gpu_mem_mb": 8192, "cpu": 8},
            },
        )

        reassigned = self.request_json(
            "POST",
            f"/training/jobs/{job['id']}/reassign",
            token=self.buyer_token,
            json={"worker_code": worker_code, "worker_host": worker_host, "note": "pin worker from api regression"},
        )
        self.assertEqual(reassigned["status"], "PENDING")
        self.assertIn(worker_code, reassigned["worker_selector"]["worker_codes"])
        self.assertIn(worker_host, reassigned["worker_selector"]["hosts"])

    def test_training_runtime_reconcile_marks_stale_jobs_and_workers(self) -> None:
        train_label = self.unique_name("api-runtime-train")
        validation_label = self.unique_name("api-runtime-val")
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

        stale_worker_code = self.unique_name("api-runtime-stale-worker")
        stale_worker_host = f"{stale_worker_code}.local"
        stale_worker = self.request_json(
            "POST",
            "/training/workers/register",
            token=self.platform_token,
            json={
                "worker_code": stale_worker_code,
                "name": "API Runtime Stale Worker",
                "host": stale_worker_host,
                "status": "ACTIVE",
                "labels": {"suite": "api-runtime", "kind": "gpu"},
                "resources": {"gpu_mem_mb": 4096},
            },
        )
        stale_worker_token = stale_worker["bootstrap_token"]

        dispatch_job = self.request_json(
            "POST",
            "/training/jobs",
            token=self.buyer_token,
            json={
                "asset_ids": [train_asset["id"]],
                "validation_asset_ids": [validation_asset["id"]],
                "base_model_id": base_model["id"],
                "training_kind": "finetune",
                "target_model_code": self.unique_name("api-runtime-dispatch"),
                "target_version": "v1.0.0",
                "worker_selector": {"hosts": [stale_worker_host]},
                "spec": {"epochs": 1},
            },
        )

        self.request_json(
            "POST",
            "/training/workers/heartbeat",
            headers=self.worker_headers(stale_worker_code, stale_worker_token),
            json={"host": stale_worker_host, "status": "ACTIVE", "labels": {"suite": "api-runtime"}, "resources": {"gpu_mem_mb": 4096}},
        )
        stale_pull = self.request_json(
            "POST",
            "/training/workers/pull-jobs",
            headers=self.worker_headers(stale_worker_code, stale_worker_token),
            json={"limit": 2},
        )
        self.assertTrue(any(row["id"] == dispatch_job["id"] for row in stale_pull["jobs"]), stale_pull)

        time.sleep(2)
        dispatch_reconciled = self.request_json(
            "POST",
            "/training/runtime/reconcile",
            token=self.platform_token,
            json={
                "note": "api regression worker stale reconcile",
                "worker_stale_seconds": 1,
                "dispatch_timeout_seconds": 60,
                "running_timeout_seconds": 60,
            },
        )
        self.assertIn(stale_worker_code, dispatch_reconciled["unhealthy_workers"])
        self.assertGreaterEqual(dispatch_reconciled["counts"]["timed_out_job_count"], 1)
        self.assertGreaterEqual(dispatch_reconciled["counts"]["unhealthy_worker_count"], 1)

        running_worker_code = self.unique_name("api-runtime-running-worker")
        running_worker_host = f"{running_worker_code}.local"
        running_worker = self.request_json(
            "POST",
            "/training/workers/register",
            token=self.platform_token,
            json={
                "worker_code": running_worker_code,
                "name": "API Runtime Running Worker",
                "host": running_worker_host,
                "status": "ACTIVE",
                "labels": {"suite": "api-runtime", "kind": "gpu"},
                "resources": {"gpu_mem_mb": 8192},
            },
        )
        running_worker_token = running_worker["bootstrap_token"]
        running_job = self.request_json(
            "POST",
            "/training/jobs",
            token=self.buyer_token,
            json={
                "asset_ids": [train_asset["id"]],
                "validation_asset_ids": [validation_asset["id"]],
                "base_model_id": base_model["id"],
                "training_kind": "finetune",
                "target_model_code": self.unique_name("api-runtime-running"),
                "target_version": "v1.0.0",
                "worker_selector": {"hosts": [running_worker_host]},
                "spec": {"epochs": 3},
            },
        )

        self.request_json(
            "POST",
            "/training/workers/heartbeat",
            headers=self.worker_headers(running_worker_code, running_worker_token),
            json={"host": running_worker_host, "status": "ACTIVE", "labels": {"suite": "api-runtime"}, "resources": {"gpu_mem_mb": 8192}},
        )
        running_pull = self.request_json(
            "POST",
            "/training/workers/pull-jobs",
            headers=self.worker_headers(running_worker_code, running_worker_token),
            json={"limit": 2},
        )
        self.assertTrue(any(row["id"] == running_job["id"] for row in running_pull["jobs"]), running_pull)
        self.request_json(
            "POST",
            "/training/workers/push-update",
            headers=self.worker_headers(running_worker_code, running_worker_token),
            json={"job_id": running_job["id"], "status": "RUNNING", "output_summary": {"stage": "training", "epoch": 1}},
        )
        running_job_detail = self.request_json("GET", f"/training/jobs/{running_job['id']}", token=self.buyer_token)
        self.assertEqual(running_job_detail["status"], "RUNNING")
        self.assertIsNotNone(running_job_detail["started_at"])
        time.sleep(5)
        running_reconciled = self.request_json(
            "POST",
            "/training/runtime/reconcile",
            token=self.platform_token,
            json={
                "note": "api regression running timeout reconcile",
                "worker_stale_seconds": 60,
                "dispatch_timeout_seconds": 60,
                "running_timeout_seconds": 1,
            },
        )

        dispatch_after = self.request_json("GET", f"/training/jobs/{dispatch_job['id']}", token=self.buyer_token)
        self.assertTrue(
            dispatch_job["job_code"] in dispatch_reconciled["failed_jobs"] or dispatch_after["status"] == "FAILED",
            dispatch_reconciled,
        )
        self.assertEqual(dispatch_after["status"], "FAILED")
        self.assertEqual(dispatch_after["alert_level"], "CRITICAL")
        self.assertEqual(dispatch_after["recommended_action"], "reassign_or_retry")
        self.assertIn("worker_stale_dispatch", str(dispatch_after["output_summary"].get("failure_category")))

        running_after = self.request_json("GET", f"/training/jobs/{running_job['id']}", token=self.buyer_token)
        self.assertTrue(
            running_job["job_code"] in running_reconciled["failed_jobs"] or running_after["status"] == "FAILED",
            running_reconciled,
        )
        self.assertEqual(running_after["status"], "FAILED")
        self.assertEqual(running_after["alert_level"], "CRITICAL")
        self.assertEqual(running_after["recommended_action"], "inspect_worker_and_retry")
        self.assertEqual(running_after["output_summary"].get("failure_category"), "running_timeout")

        workers_after = self.request_json("GET", "/training/workers", token=self.platform_token)
        stale_worker_after = next((row for row in workers_after if row["worker_code"] == stale_worker_code), None)
        running_worker_after = next((row for row in workers_after if row["worker_code"] == running_worker_code), None)
        self.assertIsNotNone(stale_worker_after)
        self.assertIsNotNone(running_worker_after)
        self.assertEqual(stale_worker_after["status"], "UNHEALTHY")
        self.assertEqual(stale_worker_after["alert_level"], "CRITICAL")
        self.assertEqual(running_worker_after["status"], "ACTIVE")
