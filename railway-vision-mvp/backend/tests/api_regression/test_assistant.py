from __future__ import annotations

from backend.tests.api_regression.helpers import ApiRegressionHelper


class AssistantRegressionTest(ApiRegressionHelper):
    def test_assistant_provider_modes_and_local_catalog(self) -> None:
        modes = self.request_json("GET", "/assistant/provider-modes", token=self.buyer_token)
        mode_ids = [str(item.get("mode") or "").strip() for item in modes.get("modes") or []]
        self.assertIn("api", mode_ids)
        self.assertIn("local", mode_ids)

        catalog = self.request_json("GET", "/assistant/local-models", token=self.buyer_token)
        models = catalog.get("models") or []
        self.assertGreaterEqual(len(models), 10)
        self.assertEqual(models[0]["repo_id"], "openai/gpt-oss-20b")
        self.assertTrue(any(row.get("repo_id") == "Qwen/Qwen3-32B" for row in models))

    def test_assistant_plan_for_inspection_mark(self) -> None:
        plan = self.request_json(
            "POST",
            "/assistant/plan",
            token=self.buyer_token,
            json={
                "goal": "我上传一张铁路货车图片，想识别定检标记，并判断下一步是直接验证现有模型还是先继续训练。",
                "current_task_type": "inspection_mark_ocr",
                "llm_mode": "local",
                "llm_selection": {"repo_id": "Qwen/Qwen3-32B", "display_name": "Qwen3-32B"},
            },
        )
        self.assertEqual(plan["inferred_task_type"], "inspection_mark_ocr")
        self.assertEqual(plan["inferred_task_label"], "定检标记识别")
        primary_action = plan.get("primary_action") or {}
        self.assertTrue(primary_action.get("title"))
        self.assertTrue(primary_action.get("path"))
        secondary_actions = plan.get("secondary_actions") or []
        self.assertGreaterEqual(len(secondary_actions), 1)

    def test_assistant_plan_rejects_empty_request(self) -> None:
        payload = self.request_json(
            "POST",
            "/assistant/plan",
            token=self.buyer_token,
            expected_status=400,
            json={"goal": "", "asset_ids": [], "llm_mode": "disabled"},
        )
        self.assertEqual(payload["detail"]["code"], "assistant_goal_required")
