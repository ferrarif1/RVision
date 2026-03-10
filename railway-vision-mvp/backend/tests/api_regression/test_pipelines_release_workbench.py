from __future__ import annotations

from backend.tests.api_regression.helpers import ApiRegressionHelper


class PipelineReleaseWorkbenchRegressionTest(ApiRegressionHelper):
    def test_pipeline_release_workbench_returns_scope_candidates(self) -> None:
        base_model = next((row for row in self.buyer_models() if row.get("model_type") == "expert"), None)
        self.assertIsNotNone(base_model, "no buyer-visible expert model found")
        pipeline_code = self.unique_name("api-pipeline-release")
        created = self.request_json(
            "POST",
            "/pipelines/register",
            token=self.platform_token,
            json={
                "pipeline_code": pipeline_code,
                "name": "API Pipeline Release Workbench",
                "version": "v1.0.0",
                "expert_map": {"object_detect": [base_model["id"]]},
                "thresholds": {"object_detect": 0.5},
                "fusion_rules": {},
                "config": {},
            },
        )
        payload = self.request_json(
            "GET",
            f"/pipelines/{created['id']}/release-workbench",
            token=self.platform_token,
        )
        self.assertEqual(payload["pipeline"]["id"], created["id"])
        self.assertTrue(payload["scope_candidates"]["devices"])
        self.assertTrue(payload["scope_candidates"]["buyers"])
        self.assertGreaterEqual(int(payload["recommended_release"]["traffic_ratio"]), 1)
