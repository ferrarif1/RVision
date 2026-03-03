import logging
import time

import httpx

from agent.api_client import EdgeApiClient
from agent.cache_store import (
    dequeue_all_pending_results,
    enqueue_pending_result,
    ensure_cache_dirs,
    get_model_dir,
    save_asset_from_b64,
)
from agent.config import settings
from agent.model_security import ModelSecurityError, verify_and_decrypt_model
from inference.pipelines import run_inference

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("edge-agent")


def flush_pending(client: EdgeApiClient) -> None:
    pending = dequeue_all_pending_results()
    if not pending:
        return

    logger.info("retry pending results: %s", len(pending))
    failed = []
    for payload in pending:
        try:
            client.push_results(payload)
            logger.info("re-pushed task result: %s", payload.get("task_id"))
        except Exception as exc:
            logger.warning("re-push failed for %s: %s", payload.get("task_id"), exc)
            failed.append(payload)

    for payload in failed:
        enqueue_pending_result(payload)


def run_once(client: EdgeApiClient) -> None:
    flush_pending(client)

    tasks_resp = client.pull_tasks(limit=3)
    tasks = tasks_resp.get("tasks", [])
    if not tasks:
        logger.info("no tasks for device=%s", settings.edge_device_code)
        return

    logger.info("received %s tasks", len(tasks))

    for task in tasks:
        task_id = task["task_id"]
        asset_id = task["asset"]["id"]
        try:
            model_artifacts = {}
            model_registry = task.get("models") or {}
            model_ids = list(model_registry.keys()) or ([task["model"]["id"]] if task.get("model") else [])
            for model_id in model_ids:
                model_payload = client.pull_model(model_id=model_id)
                artifacts = verify_and_decrypt_model(
                    model_payload=model_payload,
                    cache_models_dir=get_model_dir(),
                    edge_public_key_path=settings.edge_sign_public_key_path,
                )
                model_artifacts[model_id] = {
                    "model_hash": artifacts.model_hash,
                    "manifest": artifacts.manifest,
                    "decrypted_path": artifacts.decrypted_path,
                }

            asset_payload = client.pull_asset(asset_id=asset_id)
            local_asset_path = save_asset_from_b64(
                asset_id=asset_id,
                file_name=asset_payload["file_name"],
                file_b64=asset_payload["file_b64"],
            )

            inference_bundle = run_inference(task=task, local_asset_path=local_asset_path, model_artifacts=model_artifacts)
            result_payload = {
                "task_id": task_id,
                "status": "SUCCEEDED",
                "items": inference_bundle.get("items") or [],
                "run": inference_bundle.get("run") or {},
            }

            try:
                client.push_results(result_payload)
                logger.info("task finished and pushed: %s", task_id)
            except Exception as exc:
                logger.warning("push failed, enqueue result for task %s: %s", task_id, exc)
                enqueue_pending_result(result_payload)
        except (ModelSecurityError, httpx.HTTPError, Exception) as exc:
            logger.exception("task failed: %s", task_id)
            fail_payload = {
                "task_id": task_id,
                "status": "FAILED",
                "error_message": str(exc),
                "items": [],
            }
            try:
                client.push_results(fail_payload)
            except Exception:
                enqueue_pending_result(fail_payload)


def main() -> None:
    ensure_cache_dirs()
    client = EdgeApiClient()
    logger.info("edge agent start. backend=%s, device=%s", settings.backend_base_url, settings.edge_device_code)

    while True:
        try:
            ping = client.ping()
            logger.info("ping ok: %s", ping.get("status"))
            run_once(client)
        except Exception as exc:
            logger.warning("main loop error: %s", exc)
        time.sleep(settings.edge_poll_seconds)


if __name__ == "__main__":
    main()
