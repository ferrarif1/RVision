#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import tempfile
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve().parent / "training_worker_runner.py"
SPEC = importlib.util.spec_from_file_location("training_worker_runner", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


def main() -> None:
    mapped = MODULE.classify_trainer_exit_code(10)
    assert mapped["category"] == "config_error"
    assert mapped["retryable"] is False

    runtime = MODULE.classify_trainer_exit_code(20)
    assert runtime["category"] == "runtime_error"
    assert runtime["retryable"] is True

    signal_exit = MODULE.classify_trainer_exit_code(143)
    assert signal_exit["category"] == "signal_terminated"
    assert signal_exit["retryable"] is True

    normalized = MODULE.normalize_external_metrics(
        {
            "trainer": "custom_ocr_trainer",
            "epochs": 2,
            "learning_rate": 0.001,
            "train_loss": 0.12,
            "val_loss": 0.09,
            "val_accuracy": 0.94,
            "history": [
                {"epoch": 1, "train_loss": 0.2, "val_loss": 0.15, "val_accuracy": 0.88, "learning_rate": 0.001},
                {"epoch": 2, "train_loss": 0.12, "val_loss": 0.09, "val_accuracy": 0.94, "learning_rate": 0.0005},
            ],
            "best_checkpoint": {"epoch": 2, "metric": "val_accuracy", "value": 0.94, "path": "checkpoints/best.pt"},
        }
    )
    assert normalized["trainer_contract_version"] == MODULE.TRAINER_CONTRACT_VERSION
    assert normalized["history_count"] == 2
    assert normalized["val_score"] == 0.94
    assert normalized["best_checkpoint"]["epoch"] == 2

    with tempfile.TemporaryDirectory(prefix="vistral_worker_contract_") as tmp_dir:
        metrics_path = Path(tmp_dir) / "metrics.json"
        metrics_path.write_text(json.dumps({"trainer": "external", "history": [{"epoch": 1, "val_accuracy": 0.91}]}), encoding="utf-8")
        loaded = MODULE.load_external_metrics(metrics_path)
        assert loaded["history_count"] == 1
        assert loaded["trainer"] == "external"

    try:
        MODULE.normalize_external_metrics({"history": [{"epoch": 0}]})
    except MODULE.WorkerError:
        pass
    else:
        raise AssertionError("expected WorkerError for invalid epoch")

    print(json.dumps({"status": "ok", "contract_version": MODULE.TRAINER_CONTRACT_VERSION}, ensure_ascii=False))


if __name__ == "__main__":
    main()
