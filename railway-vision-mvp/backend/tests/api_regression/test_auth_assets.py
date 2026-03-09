from __future__ import annotations

from backend.tests.api_regression.helpers import ApiRegressionHelper


class AuthAssetsRegressionTest(ApiRegressionHelper):
    def test_login_and_me_contract(self) -> None:
        me = self.request_json("GET", "/auth/me", token=self.buyer_token)
        self.assertEqual(me["username"], "buyer_operator")
        self.assertIn("buyer_operator", me["roles"])
        self.assertEqual(me["tenant_code"], "buyer-demo-001")
        self.assertIn("task.create", me["permissions"])

    def test_login_rejects_invalid_password(self) -> None:
        payload = self.request_json(
            "POST",
            "/auth/login",
            expected_status=401,
            json={"username": "buyer_operator", "password": "wrong-password"},
        )
        self.assertEqual(payload["detail"], "Invalid username or password")

    def test_asset_upload_reuse_and_supplier_scope(self) -> None:
        file_name = self.unique_name("api-regression-image", ".jpg")
        image_bytes = self.fake_image_bytes(file_name)
        first = self.upload_asset(
            token=self.buyer_token,
            filename=file_name,
            content=image_bytes,
            asset_purpose="inference",
            use_case="car-number-ocr",
            intended_model_code="car_number_ocr",
        )
        second = self.upload_asset(
            token=self.buyer_token,
            filename=file_name,
            content=image_bytes,
            asset_purpose="inference",
            use_case="car-number-ocr",
            intended_model_code="car_number_ocr",
        )

        self.assertEqual(first["asset_type"], "image")
        self.assertEqual(second["id"], first["id"])
        self.assertTrue(second.get("reused"), second)

        listed = self.request_json("GET", f"/assets?q={file_name}", token=self.buyer_token)
        self.assertTrue(any(row["id"] == first["id"] for row in listed), listed)

        supplier_rows = self.request_json("GET", "/assets", token=self.supplier_token)
        self.assertEqual(supplier_rows, [])

    def test_nested_zip_dataset_upload_and_inference_rejection(self) -> None:
        dataset_label = self.unique_name("api-regression-dataset")
        zip_name = f"{dataset_label}.zip"
        zip_bytes = self.nested_dataset_zip(dataset_label, media_count=2)

        uploaded = self.upload_asset(
            token=self.buyer_token,
            filename=zip_name,
            content=zip_bytes,
            asset_purpose="training",
            use_case="railcar-number-training",
            intended_model_code="car_number_ocr",
            dataset_label=dataset_label,
        )
        meta = uploaded["meta"]
        self.assertEqual(uploaded["asset_type"], "archive")
        self.assertEqual(meta["archive_resource_count"], 2)
        self.assertGreaterEqual(meta["archive_max_depth"], 2)
        self.assertEqual(meta["dataset_label"], dataset_label)

        rejected = self.request_json(
            "POST",
            "/assets/upload",
            token=self.buyer_token,
            expected_status=400,
            files={"file": (zip_name, zip_bytes, "application/zip")},
            data={
                "sensitivity_level": "L2",
                "asset_purpose": "inference",
                "dataset_label": dataset_label,
                "use_case": "railcar-number-training",
                "intended_model_code": "car_number_ocr",
            },
        )
        self.assertIn("ZIP dataset asset is only allowed", rejected["detail"])
