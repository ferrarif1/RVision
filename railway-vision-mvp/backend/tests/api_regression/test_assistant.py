from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
BACKEND_ROOT = REPO_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.assistant_paths import build_training_path, build_workflow_path
from app.services.ai_provider_service import resolve_provider_config
from app.services.ai_settings_service import delete_ai_provider_config, upsert_ai_provider_config
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
        self.assertEqual(primary_action.get("expert_path"), primary_action.get("path"))
        self.assertEqual(primary_action.get("workflow_path"), "ai/workflow/train")
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

    def test_assistant_route_mapping_helpers(self) -> None:
        self.assertEqual(build_training_path("car_number_ocr"), "training/car-number-labeling")
        self.assertEqual(build_training_path("inspection_mark_ocr"), "training/inspection-ocr/inspection_mark_ocr")
        self.assertEqual(build_training_path("bolt_missing_detect"), "training/inspection-state/bolt_missing_detect")
        self.assertEqual(build_workflow_path("upload_or_select_assets", "assets"), "ai/workflow/upload")
        self.assertEqual(build_workflow_path("prepare_training_data", "training"), "ai/workflow/train")
        self.assertEqual(build_workflow_path("open_release_workbench", "models"), "ai/workflow/deploy")
        self.assertEqual(build_workflow_path("validate_existing_model", "tasks"), "ai/workflow/results")

    def test_scoped_provider_selection_prefers_matching_scope(self) -> None:
        global_provider = upsert_ai_provider_config({
            "name": self.unique_name("provider-global"),
            "provider": "openai_compatible",
            "mode": "api",
            "base_url": "https://global.example.com",
            "api_path": "/v1",
            "model_name": "global-model",
            "enabled": True,
            "is_default": True,
            "scope": ["global"],
        })
        results_provider = upsert_ai_provider_config({
            "name": self.unique_name("provider-results"),
            "provider": "openai_compatible",
            "mode": "api",
            "base_url": "https://results.example.com",
            "api_path": "/v1",
            "model_name": "results-model",
            "enabled": True,
            "is_default": False,
            "scope": ["results"],
        })
        try:
            scoped = resolve_provider_config(llm_mode="api", workflow_scope="results", llm_selection={}, api_config={})
            self.assertIsNotNone(scoped)
            self.assertEqual(scoped["id"], results_provider["id"])
            fallback = resolve_provider_config(llm_mode="api", workflow_scope="train", llm_selection={}, api_config={})
            self.assertIsNotNone(fallback)
            self.assertEqual(fallback["id"], global_provider["id"])
        finally:
            delete_ai_provider_config(results_provider["id"])
            delete_ai_provider_config(global_provider["id"])

    def test_ai_settings_and_context_injection(self) -> None:
        provider_name = self.unique_name("provider")
        doc_title = self.unique_name("knowledge")
        created_provider = self.request_json(
            "POST",
            "/settings/ai/providers",
            token=self.platform_token,
            json={
                "name": provider_name,
                "provider": "openai_compatible",
                "mode": "api",
                "base_url": "",
                "api_path": "/v1",
                "model_name": "mock-model",
                "enabled": False,
                "is_default": False,
            },
        )
        provider_id = created_provider["id"]
        created_doc = self.request_json(
            "POST",
            "/settings/ai/knowledge",
            token=self.platform_token,
            json={
                "title": doc_title,
                "description": "回归测试知识条目",
                "content": "当用户提到回归测试知识条目时，AI 应知道这是管理员录入的自定义知识。",
                "scope": ["global", "results"],
                "enabled": True,
            },
        )
        doc_id = created_doc["id"]
        try:
            provider_list = self.request_json("GET", "/settings/ai/providers", token=self.platform_token)
            self.assertTrue(any(row.get("id") == provider_id for row in provider_list.get("providers") or []))

            test_result = self.request_json(
                "POST",
                "/settings/ai/providers/test",
                token=self.platform_token,
                json={
                    "id": provider_id,
                    "name": provider_name,
                    "provider": "openai_compatible",
                    "mode": "api",
                    "base_url": "",
                    "api_path": "/v1",
                    "model_name": "mock-model",
                },
            )
            self.assertFalse(test_result["ok"])
            provider_list_after_test = self.request_json("GET", "/settings/ai/providers", token=self.platform_token)
            tested_provider = next((row for row in provider_list_after_test.get("providers") or [] if row.get("id") == provider_id), None)
            self.assertIsNotNone(tested_provider)
            self.assertIsNotNone((tested_provider or {}).get("last_test_result"))
            self.assertFalse((tested_provider or {}).get("last_test_result", {}).get("ok"))

            behavior = self.request_json(
                "PUT",
                "/settings/ai/behavior",
                token=self.platform_token,
                json={
                    "system_prompt": "你是回归测试专用 AI 助手。",
                    "strict_document_mode": True,
                    "allow_freeform_suggestions": False,
                    "prefer_workflow_jump": True,
                    "show_reasoning_summary": True,
                    "allow_auto_prefill": True,
                },
            )
            self.assertEqual(behavior["system_prompt"], "你是回归测试专用 AI 助手。")
            self.assertTrue(behavior["strict_document_mode"])

            plan = self.request_json(
                "POST",
                "/assistant/plan",
                token=self.buyer_token,
                json={
                    "goal": "我需要结合回归测试知识条目判断下一步，先看结果再决定是否继续训练。",
                    "current_task_type": "car_number_ocr",
                    "llm_mode": "disabled",
                    "llm_selection": {},
                    "api_config": {},
                },
            )
            context_docs = plan.get("context_documents") or []
            self.assertTrue(any(row.get("id") == doc_id for row in context_docs))
            self.assertTrue(any(row.get("id") == "system_overview" for row in context_docs))
            self.assertEqual(plan.get("behavior_settings", {}).get("system_prompt"), "你是回归测试专用 AI 助手。")
        finally:
            self.request_json("DELETE", f"/settings/ai/knowledge/{doc_id}", token=self.platform_token)
            self.request_json("DELETE", f"/settings/ai/providers/{provider_id}", token=self.platform_token)
