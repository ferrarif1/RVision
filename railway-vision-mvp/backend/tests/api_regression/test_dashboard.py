from .helpers import ApiRegressionHelper


class DashboardRegressionTest(ApiRegressionHelper):
    def test_dashboard_summary_hides_synthetic_assets(self) -> None:
        before = self.request_json("GET", "/dashboard/summary", token=self.platform_token)
        before_assets = int(before["lanes"]["line1_assets"]["total_assets"])
        before_hidden = int(before.get("hygiene", {}).get("hidden_assets", 0))

        real_asset_name = self.unique_name("dashboard-real", ".jpg")
        synthetic_asset_name = self.unique_name("api-regression-dashboard", ".jpg")

        self.upload_asset(
            token=self.platform_token,
            filename=real_asset_name,
            content=self.fake_image_bytes("dashboard-real"),
            asset_purpose="inference",
            use_case="dashboard_real_asset",
            intended_model_code="car_number_ocr",
        )
        self.upload_asset(
            token=self.platform_token,
            filename=synthetic_asset_name,
            content=self.fake_image_bytes("dashboard-synthetic"),
            asset_purpose="inference",
            use_case="api-regression-dashboard",
            intended_model_code="api-regression-model",
        )

        after = self.request_json("GET", "/dashboard/summary", token=self.platform_token)
        after_assets = int(after["lanes"]["line1_assets"]["total_assets"])
        after_hidden = int(after.get("hygiene", {}).get("hidden_assets", 0))
        recent_asset_names = [str(row.get("file_name") or "") for row in after.get("recent", {}).get("assets", [])]

        self.assertEqual(after_assets, before_assets + 1)
        self.assertGreaterEqual(after_hidden, before_hidden + 1)
        self.assertIn(real_asset_name, recent_asset_names)
        self.assertNotIn(synthetic_asset_name, recent_asset_names)
