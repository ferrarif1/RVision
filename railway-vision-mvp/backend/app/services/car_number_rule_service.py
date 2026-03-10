from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status

REPO_ROOT = Path(__file__).resolve().parents[3]
RULE_CONFIG_CANDIDATES = (
    REPO_ROOT / "config" / "car_number_rules.json",
    Path("/app/config/car_number_rules.json"),
)
DEFAULT_RULE_ID = "railcar_digits_v1"
DEFAULT_RULE = {
    "rule_id": DEFAULT_RULE_ID,
    "label": "铁路车号 · 8位数字",
    "description": "当前默认要求车号为 8 位数字。",
    "pattern": r"^\d{8}$",
    "normalization": "uppercase_alnum",
    "examples": ["64345127", "62745500"],
    "notes": "后续如果规则变化，只需切换 active_rule 或更新对应 pattern。",
}


def normalize_car_number_text(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


@lru_cache(maxsize=1)
def _load_rule_payload() -> dict[str, Any]:
    config_path = next((path for path in RULE_CONFIG_CANDIDATES if path.exists()), None)
    if config_path is None:
        return {"active_rule": DEFAULT_RULE_ID, "rules": {DEFAULT_RULE_ID: DEFAULT_RULE}}
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {"active_rule": DEFAULT_RULE_ID, "rules": {DEFAULT_RULE_ID: DEFAULT_RULE}}
    if not isinstance(payload, dict):
        return {"active_rule": DEFAULT_RULE_ID, "rules": {DEFAULT_RULE_ID: DEFAULT_RULE}}
    return payload


def get_active_car_number_rule() -> dict[str, Any]:
    payload = _load_rule_payload()
    active_rule = str(payload.get("active_rule") or DEFAULT_RULE_ID).strip() or DEFAULT_RULE_ID
    rules = payload.get("rules") if isinstance(payload.get("rules"), dict) else {}
    rule = rules.get(active_rule) if isinstance(rules.get(active_rule), dict) else None
    merged = {**DEFAULT_RULE, **(rule or {})}
    merged["rule_id"] = active_rule
    merged["pattern"] = str(merged.get("pattern") or DEFAULT_RULE["pattern"])
    return merged


def validate_car_number_text(value: Any) -> dict[str, Any]:
    normalized = normalize_car_number_text(value)
    rule = get_active_car_number_rule()
    pattern = str(rule.get("pattern") or DEFAULT_RULE["pattern"])
    valid = bool(normalized and re.fullmatch(pattern, normalized))
    return {
        "valid": valid,
        "normalized_text": normalized,
        "rule_id": rule["rule_id"],
        "label": rule["label"],
        "description": rule["description"],
        "pattern": pattern,
        "examples": list(rule.get("examples") or []),
        "notes": rule.get("notes"),
    }


def ensure_valid_car_number_text(value: Any, *, field_name: str = "car_number") -> dict[str, Any]:
    validation = validate_car_number_text(value)
    if not validation["normalized_text"]:
        return validation
    if validation["valid"]:
        return validation
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"{field_name} does not match active rule {validation['rule_id']}: {validation['description']}",
    )
