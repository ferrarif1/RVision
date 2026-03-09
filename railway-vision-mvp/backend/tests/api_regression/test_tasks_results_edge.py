from __future__ import annotations

import time

from backend.tests.api_regression.helpers import ApiRegressionHelper, EDGE_DEVICE_CODE


class TasksResultsEdgeRegressionTest(ApiRegressionHelper):
    def test_preflight_inspect_suggests_car_number_candidate(self) -> None:
        image_name = "CAR123456_demo.png"
        asset = self.upload_asset(
            token=self.buyer_token,
            filename=image_name,
            content=self.tiny_png_bytes(),
            asset_purpose="inference",
            use_case="quick-detect-preflight",
            intended_model_code="car_number_ocr",
        )

        preflight = self.request_json(
            "POST",
            "/tasks/preflight-inspect",
            token=self.buyer_token,
            json={
                "asset_id": asset["id"],
                "device_code": EDGE_DEVICE_CODE,
                "prompt_hint": "车号",
                "wait_timeout_seconds": 25,
            },
        )
        selected = preflight["selected_candidate"]
        self.assertIsNotNone(selected, preflight)
        self.assertEqual(selected["task_type"], "car_number_ocr")
        self.assertGreaterEqual(int(selected["score"]), 25, selected)

    def test_car_number_recommendation_and_text_review(self) -> None:
        image_name = self.unique_name("api-car-number", ".jpg")
        asset = self.upload_asset(
            token=self.buyer_token,
            filename=image_name,
            content=self.fake_image_bytes(image_name),
            asset_purpose="inference",
            use_case="railcar-number-ocr",
            intended_model_code="car_number_ocr",
        )

        decision = self.schedulable_model(asset_id=asset["id"], task_type=None, intent_text="识别车号内容 车厢号 编号")
        selected = decision["selected_model"]
        self.assertIsNotNone(selected, decision)
        self.assertEqual(selected["task_type"], "car_number_ocr")

        task = self.request_json(
            "POST",
            "/tasks/create",
            token=self.buyer_token,
            json={
                "asset_id": asset["id"],
                "model_id": selected["model_id"],
                "task_type": selected["task_type"],
                "device_code": EDGE_DEVICE_CODE,
                "intent_text": "识别车号内容",
            },
        )

        pulled = None
        pulled_tasks = {"tasks": []}
        for _ in range(12):
            pulled_tasks = self.request_json("POST", "/edge/pull_tasks", headers=self.edge_headers(), json={"limit": 20})
            pulled = next((row for row in pulled_tasks["tasks"] if row["task_id"] == task["id"]), None)
            if pulled:
                break
            time.sleep(0.5)
        self.assertIsNotNone(pulled, pulled_tasks)

        pushed = self.request_json(
            "POST",
            "/edge/push_results",
            headers=self.edge_headers(),
            json={
                "task_id": task["id"],
                "status": "SUCCEEDED",
                "items": [
                    {
                        "model_id": task["model_id"],
                        "model_hash": selected["model_hash"],
                        "alert_level": "INFO",
                        "result_json": {
                            "task_type": "car_number_ocr",
                            "predictions": [{"label": "car_number", "text": "RV10086", "score": 0.98, "bbox": [20, 24, 180, 86]}],
                            "matched_labels": ["car_number"],
                            "object_count": 1,
                            "summary": {"task_type": "car_number_ocr", "car_number": "RV10086", "confidence": 0.98, "bbox": [20, 24, 180, 86]},
                        },
                        "duration_ms": 31,
                        "screenshot_b64": self.screenshot_b64("car-number-text"),
                    }
                ],
                "run": {
                    "job_id": self.unique_name("run"),
                    "pipeline_version": "api-car-number",
                    "threshold_version": "v1",
                    "input_hash": self.unique_name("hash"),
                    "models_versions": [{"model_id": task["model_id"], "version": selected["version"]}],
                    "timings": {"total_ms": 31},
                    "result_summary": {"car_number": "RV10086"},
                },
            },
        )
        self.assertEqual(pushed["status"], "SUCCEEDED")

        results = self.request_json("GET", f"/results?task_id={task['id']}", token=self.buyer_token)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["result_json"]["summary"]["car_number"], "RV10086")

        reviewed = self.request_json(
            "POST",
            f"/results/{results[0]['id']}/review",
            token=self.buyer_token,
            json={
                "predictions": [{"label": "car_number", "text": "RV10087", "score": 0.99, "bbox": [20, 24, 180, 86]}],
                "note": "corrected ocr text",
            },
        )
        reviewed_json = reviewed["result"]["result_json"]
        self.assertEqual(reviewed_json["predictions"][0]["text"], "RV10087")
        self.assertEqual(reviewed_json["summary"]["car_number"], "RV10087")

    def test_task_edge_result_dataset_flow(self) -> None:
        image_name = self.unique_name("api-regression-task", ".jpg")
        asset = self.upload_asset(
            token=self.buyer_token,
            filename=image_name,
            content=self.fake_image_bytes(image_name),
            asset_purpose="inference",
            use_case="object-detect",
            intended_model_code="object_detect",
        )

        decision = self.schedulable_model(asset_id=asset["id"], task_type="object_detect", intent_text="car")
        selected = decision["selected_model"]
        task = self.request_json(
            "POST",
            "/tasks/create",
            token=self.buyer_token,
            json={
                "asset_id": asset["id"],
                "model_id": selected["model_id"],
                "task_type": selected["task_type"],
                "device_code": EDGE_DEVICE_CODE,
                "context": {"scene_hint": "yard-west"},
            },
        )
        task_detail = self.request_json("GET", f"/tasks/{task['id']}", token=self.buyer_token)
        self.assertEqual(task_detail["status"], "PENDING")
        self.assertEqual(task_detail["asset_id"], asset["id"])

        ping = self.request_json("GET", "/edge/ping", headers=self.edge_headers())
        self.assertEqual(ping["device_code"], EDGE_DEVICE_CODE)

        pulled = None
        pulled_tasks = {"tasks": []}
        for _ in range(12):
            pulled_tasks = self.request_json("POST", "/edge/pull_tasks", headers=self.edge_headers(), json={"limit": 20})
            pulled = next((row for row in pulled_tasks["tasks"] if row["task_id"] == task["id"]), None)
            if pulled:
                break
            time.sleep(0.5)
        self.assertIsNotNone(pulled, pulled_tasks)

        pulled_asset = self.request_json("GET", f"/edge/pull_asset?asset_id={asset['id']}", headers=self.edge_headers())
        self.assertEqual(pulled_asset["asset_id"], asset["id"])
        self.assertTrue(pulled_asset["file_b64"])

        pulled_model = self.request_json(
            "POST",
            "/edge/pull_model",
            headers=self.edge_headers(),
            json={"model_id": task["model_id"]},
        )
        self.assertEqual(pulled_model["model_id"], task["model_id"])
        self.assertTrue(pulled_model["manifest_b64"])

        pushed = self.request_json(
            "POST",
            "/edge/push_results",
            headers=self.edge_headers(),
            json={
                "task_id": task["id"],
                "status": "SUCCEEDED",
                "items": [
                    {
                        "model_id": task["model_id"],
                        "model_hash": selected["model_hash"],
                        "alert_level": "INFO",
                        "result_json": {
                            "predictions": [{"label": "car", "score": 0.97, "bbox": [10, 20, 100, 140]}],
                            "matched_labels": ["car"],
                            "object_count": 1,
                        },
                        "duration_ms": 42,
                        "screenshot_b64": self.screenshot_b64("task-flow"),
                    }
                ],
                "run": {
                    "job_id": self.unique_name("run"),
                    "pipeline_version": "api-regression",
                    "threshold_version": "v1",
                    "input_hash": self.unique_name("hash"),
                    "models_versions": [{"model_id": task["model_id"], "version": selected["version"]}],
                    "timings": {"total_ms": 42},
                    "result_summary": {"object_count": 1},
                    "review_reasons": ["manual_verification"],
                },
            },
        )
        self.assertEqual(pushed["status"], "SUCCEEDED")
        self.assertEqual(pushed["saved_results"], 1)

        pushed_again = self.request_json(
            "POST",
            "/edge/push_results",
            headers=self.edge_headers(),
            json={
                "task_id": task["id"],
                "status": "SUCCEEDED",
                "items": [],
                "run": {},
            },
        )
        self.assertTrue(pushed_again["idempotent"])

        task_after = self.request_json("GET", f"/tasks/{task['id']}", token=self.buyer_token)
        self.assertEqual(task_after["status"], "SUCCEEDED")
        self.assertEqual(task_after["result_count"], 1)
        self.assertTrue(task_after["review_queue"])

        results = self.request_json("GET", f"/results?task_id={task['id']}", token=self.buyer_token)
        self.assertEqual(len(results), 1)
        result_id = results[0]["id"]

        reviewed = self.request_json(
            "POST",
            f"/results/{result_id}/review",
            token=self.buyer_token,
            json={
                "predictions": [{"label": "car_confirmed", "score": 0.99, "bbox": [12, 18, 102, 144]}],
                "note": "confirmed in API regression",
            },
        )
        result_json = reviewed["result"]["result_json"]
        self.assertEqual(result_json["review_status"], "revised")
        self.assertEqual(result_json["matched_labels"], ["car_confirmed"])

        exported = self.request_json("GET", f"/results/export?task_id={task['id']}", token=self.buyer_token)
        self.assertEqual(exported["count"], 1)
        self.assertEqual(exported["run"]["result_summary"]["object_count"], 1)

        dataset_label = self.unique_name("api-regression-result-dataset")
        dataset_export = self.request_json(
            "POST",
            "/results/export-dataset",
            token=self.buyer_token,
            json={
                "task_ids": [task["id"]],
                "dataset_label": dataset_label,
                "asset_purpose": "training",
                "include_screenshots": True,
            },
        )
        dataset_version_id = dataset_export["dataset_version"]["id"]
        self.assertEqual(dataset_export["dataset_version"]["dataset_label"], dataset_label)

        versions = self.request_json("GET", f"/assets/dataset-versions?q={dataset_label}", token=self.buyer_token)
        self.assertTrue(any(row["id"] == dataset_version_id for row in versions), versions)

        recommended = self.request_json(
            "POST",
            f"/assets/dataset-versions/{dataset_version_id}/recommend",
            token=self.buyer_token,
            json={"asset_purpose": "training", "note": "api regression recommended dataset"},
        )
        self.assertTrue(recommended["dataset_version"]["recommended"])

        preview = self.request_json(
            "GET",
            f"/assets/dataset-versions/{dataset_version_id}/preview?sample_limit=3",
            token=self.buyer_token,
        )
        self.assertEqual(preview["dataset_version"]["id"], dataset_version_id)
        self.assertTrue(preview["samples"])

        reviewed_second = self.request_json(
            "POST",
            f"/results/{result_id}/review",
            token=self.buyer_token,
            json={
                "predictions": [{"label": "car_rechecked", "score": 0.995, "bbox": [11, 19, 103, 145]}],
                "note": "second pass review for compare filter coverage",
            },
        )
        self.assertEqual(reviewed_second["result"]["result_json"]["matched_labels"], ["car_rechecked"])

        dataset_export_second = self.request_json(
            "POST",
            "/results/export-dataset",
            token=self.buyer_token,
            json={
                "task_ids": [task["id"]],
                "dataset_label": dataset_label,
                "asset_purpose": "training",
                "include_screenshots": True,
            },
        )
        second_version_id = dataset_export_second["dataset_version"]["id"]
        self.assertNotEqual(second_version_id, dataset_version_id)

        compare_filtered = self.request_json(
            "GET",
            f"/assets/dataset-versions/compare?left_id={dataset_version_id}&right_id={second_version_id}&change_scope=changed&changed_field=matched_labels&label=car_rechecked",
            token=self.buyer_token,
        )
        self.assertEqual(compare_filtered["diff"]["sample_changed_count"], 1)
        self.assertEqual(compare_filtered["diff"]["filtered_sample_count"], 1)
        self.assertEqual(len(compare_filtered["diff"]["changed_samples"]), 1)
        self.assertEqual(compare_filtered["diff"]["changed_samples"][0]["right"]["matched_labels"], ["car_rechecked"])

        rolled_back = self.request_json(
            "POST",
            f"/assets/dataset-versions/{second_version_id}/rollback",
            token=self.buyer_token,
            json={"asset_purpose": "training", "note": "api regression rollback"},
        )
        rollback_version = rolled_back["dataset_version"]
        self.assertEqual(rollback_version["source_type"], "rollback")
        self.assertEqual(rolled_back["rolled_back_from"]["id"], second_version_id)

        versions_after = self.request_json("GET", f"/assets/dataset-versions?q={dataset_label}", token=self.buyer_token)
        self.assertTrue(any(row["id"] == rollback_version["id"] for row in versions_after), versions_after)
