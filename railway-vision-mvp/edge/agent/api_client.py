from typing import Any

import httpx

from agent.config import settings


class EdgeApiClient:
    def __init__(self):
        self.base_url = settings.backend_base_url.rstrip("/")
        self.headers = {
            "x-edge-device-code": settings.edge_device_code,
            "x-edge-token": settings.edge_token,
            "content-type": "application/json",
        }

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def ping(self) -> dict[str, Any]:
        with httpx.Client(timeout=30.0, verify=settings.verify_tls) as client:
            resp = client.get(self._url("/edge/ping"), headers=self.headers)
            resp.raise_for_status()
            return resp.json()

    def pull_tasks(self, limit: int = 3) -> dict[str, Any]:
        with httpx.Client(timeout=60.0, verify=settings.verify_tls) as client:
            resp = client.post(self._url("/edge/pull_tasks"), json={"limit": limit}, headers=self.headers)
            resp.raise_for_status()
            return resp.json()

    def pull_model(self, model_id: str) -> dict[str, Any]:
        with httpx.Client(timeout=120.0, verify=settings.verify_tls) as client:
            resp = client.post(self._url("/edge/pull_model"), json={"model_id": model_id}, headers=self.headers)
            resp.raise_for_status()
            return resp.json()

    def pull_asset(self, asset_id: str) -> dict[str, Any]:
        with httpx.Client(timeout=120.0, verify=settings.verify_tls) as client:
            resp = client.get(self._url(f"/edge/pull_asset?asset_id={asset_id}"), headers=self.headers)
            resp.raise_for_status()
            return resp.json()

    def push_results(self, payload: dict[str, Any]) -> dict[str, Any]:
        with httpx.Client(timeout=120.0, verify=settings.verify_tls) as client:
            resp = client.post(self._url("/edge/push_results"), json=payload, headers=self.headers)
            resp.raise_for_status()
            return resp.json()
