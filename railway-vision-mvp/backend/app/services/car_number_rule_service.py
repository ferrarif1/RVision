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
DEFAULT_RULE_ID = "railcar_identifier_family_v1"
DEFAULT_RULE = {
    "rule_id": DEFAULT_RULE_ID,
    "label": "铁路货车标识 · 多规则族",
    "description": "当前按库内巡检场景接受标准 8 位数字车号、字母前缀数字编号和紧凑型混合编号。",
    "pattern": r"^(?:\d{8}|[A-Z]{1,3}\d{5,8}|(?=.*[A-Z])(?=.*\d)[A-Z0-9]{6,12})$",
    "normalization": "uppercase_alnum",
    "examples": ["64345127", "62745500", "CAR123456", "KM545308"],
    "notes": "活动规则族。后续如需新增车型代码、定检编号等规则，只需补充 accepted_rules。",
    "accepted_rules": ["railcar_digits_v1", "railcar_alnum_prefix_v1", "railcar_mixed_compact_v1"],
    "primary_rule": "railcar_digits_v1",
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
    accepted_rules = []
    for rule_id in merged.get("accepted_rules") or []:
        if not isinstance(rule_id, str) or not rule_id.strip():
            continue
        nested = rules.get(rule_id) if isinstance(rules.get(rule_id), dict) else None
        if not nested:
            continue
        accepted_rules.append(
            {
                "rule_id": rule_id,
                "label": str(nested.get("label") or rule_id),
                "description": str(nested.get("description") or ""),
                "pattern": str(nested.get("pattern") or ""),
                "examples": list(nested.get("examples") or []),
            }
        )
    merged["accepted_rule_details"] = accepted_rules
    return merged


def validate_car_number_text(value: Any) -> dict[str, Any]:
    normalized = normalize_car_number_text(value)
    rule = get_active_car_number_rule()
    pattern = str(rule.get("pattern") or DEFAULT_RULE["pattern"])
    matched_rule_id = ""
    matched_rule_label = ""
    valid = False
    accepted_rule_details = list(rule.get("accepted_rule_details") or [])
    for item in accepted_rule_details:
        item_pattern = str(item.get("pattern") or "").strip()
        if item_pattern and normalized and re.fullmatch(item_pattern, normalized):
            valid = True
            matched_rule_id = str(item.get("rule_id") or "")
            matched_rule_label = str(item.get("label") or matched_rule_id)
            break
    if not valid:
        valid = bool(normalized and re.fullmatch(pattern, normalized))
        if valid:
            matched_rule_id = str(rule.get("rule_id") or "")
            matched_rule_label = str(rule.get("label") or matched_rule_id)
    return {
        "valid": valid,
        "normalized_text": normalized,
        "rule_id": rule["rule_id"],
        "label": rule["label"],
        "description": rule["description"],
        "pattern": pattern,
        "accepted_rules": [str(item.get("rule_id") or "") for item in accepted_rule_details if str(item.get("rule_id") or "").strip()],
        "accepted_rule_details": accepted_rule_details,
        "matched_rule_id": matched_rule_id or None,
        "matched_rule_label": matched_rule_label or None,
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
        detail=f"{field_name} does not match accepted rules of {validation['rule_id']}: {validation['description']}",
    )
