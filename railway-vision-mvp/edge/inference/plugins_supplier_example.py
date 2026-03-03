"""Example external plugin module for supplier-provided algorithm handlers.

Enable by setting:
  EDGE_PLUGIN_MODULES=inference.plugins_supplier_example
"""

import time

from inference.pipelines import ModelExecutionContext


class SupplierExamplePlugin:
    plugin_names = ("supplier_example_detect",)

    def run(self, ctx: ModelExecutionContext) -> dict:
        started = time.time()
        # Placeholder logic for external supplier plugin integration.
        # Real implementation can load supplier model/runtime and return
        # normalized predictions/artifacts/metrics expected by the orchestrator.
        return {
            "predictions": [
                {
                    "label": "supplier_example_detect",
                    "score": 0.9,
                    "attributes": {"asset_path": ctx.local_asset_path},
                }
            ],
            "artifacts": [],
            "metrics": {
                "duration_ms": int((time.time() - started) * 1000),
                "gpu_mem_mb": 0,
                "version": ctx.model_meta.get("version") or ctx.manifest.get("version"),
                "calibration": "supplier-default",
            }
,
            "summary": {
                "task_type": "supplier_example_detect",
                "message": "supplier example plugin executed",
            },
        }


def register_plugins(register) -> None:
    register(SupplierExamplePlugin())
