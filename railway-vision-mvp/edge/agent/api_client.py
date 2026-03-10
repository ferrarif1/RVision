from typing import Any

import httpx

from agent.config import settings


class EdgeApiClient:
    def __init__(self):
        # 统一注入设备身份头，中心端按设备维度做鉴权和审计。
        # Inject device identity headers for control-plane auth and auditing.
        self.base_url = settings.backend_base_url.rstrip("/")
        self.headers = {
            "x-edge-device-code": settings.edge_device_code,
            "x-edge-token": settings.edge_token,
            "x-edge-agent-version": settings.edge_agent_version,
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
        # limit 控制单次拉取批量，避免边缘端一次性抢占过多任务。
        # `limit` caps batch size to avoid over-fetching.
        with httpx.Client(timeout=60.0, verify=settings.verify_tls) as client:
            resp = client.post(self._url("/edge/pull_tasks"), json={"limit": limit}, headers=self.headers)
            resp.raise_for_status()
            return resp.json()

    def pull_model(self, model_id: str, task_id: str | None = None) -> dict[str, Any]:
        with httpx.Client(timeout=120.0, verify=settings.verify_tls) as client:
            resp = client.post(
                self._url("/edge/pull_model"),
                json={"model_id": model_id, "task_id": task_id},
                headers=self.headers,
            )
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
