from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def parse_route_overflow_artifacts(stage_dir: Path, canonical_grid: dict[str, Any]) -> dict[str, Any]:
    """Parse router-native per-gcell/per-patch overflow artifacts when present."""
    for path in _candidate_paths(stage_dir):
        records = _read_records(path)
        if not records:
            continue
        labels = _labels_from_records(records, canonical_grid, path)
        if labels:
            return {"available": True, "source": str(path), "labels": labels}
    return {"available": False, "source": None, "labels": []}


def _candidate_paths(stage_dir: Path) -> list[Path]:
    roots = [stage_dir / "data" / "rt", stage_dir / "feature", stage_dir / "analysis"]
    names = [
        "patch_overflow.json",
        "patch_overflow.jsonl",
        "route_patch_overflow.json",
        "route_patch_overflow.jsonl",
        "gcell_overflow.json",
        "gcell_overflow.jsonl",
    ]
    return [root / name for root in roots for name in names if (root / name).exists()]


def _read_records(path: Path) -> list[dict[str, Any]]:
    try:
        if path.suffix == ".jsonl":
            return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return []
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("patches", "gcells", "records", "overflow"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


def _labels_from_records(records: list[dict[str, Any]], canonical_grid: dict[str, Any], path: Path) -> list[dict[str, Any]]:
    patch_totals = {
        int(patch["patch_id"]): {
            "patch_id": int(patch["patch_id"]),
            "row": int(patch["row"]),
            "col": int(patch["col"]),
            "gcell": patch.get("gcell", {}),
            "horizontal_overflow": 0.0,
            "vertical_overflow": 0.0,
            "by_layer": {},
            "source": "router_native_overflow",
            "source_artifacts": {"route_overflow": str(path)},
        }
        for patch in canonical_grid.get("patches", [])
    }
    patches_by_coord = {(item["row"], item["col"]): patch_id for patch_id, item in patch_totals.items()}
    patches_by_gcell = {}
    for patch_id, item in patch_totals.items():
        gcell = item.get("gcell")
        if not isinstance(gcell, dict) or gcell.get("x") is None or gcell.get("y") is None:
            continue
        patches_by_gcell[(int(gcell["x"]), int(gcell["y"]))] = patch_id
    for record in records:
        patch_id = _record_patch_id(record, canonical_grid, patches_by_coord, patches_by_gcell)
        if patch_id is None or patch_id not in patch_totals:
            continue
        direction = str(record.get("direction") or record.get("orient") or "").lower()
        if direction not in {"horizontal", "vertical"}:
            direction = "horizontal" if direction in {"h", "x"} else "vertical" if direction in {"v", "y"} else ""
        overflow = _overflow(record)
        if overflow is None:
            continue
        demand = _float_or_none(record.get("demand"))
        capacity = _float_or_none(record.get("capacity"))
        item = patch_totals[patch_id]
        layer = str(record.get("layer") or record.get("layer_name") or "unknown")
        layer_item = item["by_layer"].setdefault(layer, {"horizontal": 0.0, "vertical": 0.0})
        if direction == "vertical":
            item["vertical_overflow"] += overflow
            _accumulate_optional(item, "vertical_demand", demand)
            _accumulate_optional(item, "vertical_capacity", capacity)
            _accumulate_optional(layer_item, "vertical_demand", demand)
            _accumulate_optional(layer_item, "vertical_capacity", capacity)
            layer_item["vertical"] += overflow
        else:
            item["horizontal_overflow"] += overflow
            _accumulate_optional(item, "horizontal_demand", demand)
            _accumulate_optional(item, "horizontal_capacity", capacity)
            _accumulate_optional(layer_item, "horizontal_demand", demand)
            _accumulate_optional(layer_item, "horizontal_capacity", capacity)
            layer_item["horizontal"] += overflow
    labels = []
    for item in patch_totals.values():
        h = float(item["horizontal_overflow"])
        v = float(item["vertical_overflow"])
        labels.append({**item, **_demand_capacity_fields(item), "union_overflow": max(h, v)})
    return labels


def _record_patch_id(
    record: dict[str, Any],
    canonical_grid: dict[str, Any],
    patches_by_coord: dict[tuple[int, int], int],
    patches_by_gcell: dict[tuple[int, int], int],
) -> int | None:
    raw_patch_id = record.get("patch_id")
    if raw_patch_id is not None:
        try:
            return int(raw_patch_id)
        except (TypeError, ValueError):
            return None
    row = record.get("row")
    col = record.get("col")
    if row is not None and col is not None:
        try:
            return patches_by_coord.get((int(row), int(col)))
        except (TypeError, ValueError):
            return None
    x = record.get("x")
    y = record.get("y")
    if x is None or y is None:
        gcell = record.get("gcell")
        if isinstance(gcell, list | tuple) and len(gcell) >= 2:
            try:
                gcell_key = (int(gcell[0]), int(gcell[1]))
            except (TypeError, ValueError):
                return None
            if gcell_key in patches_by_gcell:
                return patches_by_gcell[gcell_key]
            x, y = gcell[0], gcell[1]
    if x is None or y is None:
        return None
    for patch in canonical_grid.get("patches", []):
        bbox = patch["bbox"]
        if float(bbox["llx"]) <= float(x) <= float(bbox["urx"]) and float(bbox["lly"]) <= float(y) <= float(bbox["ury"]):
            return int(patch["patch_id"])
    return None


def _overflow(record: dict[str, Any]) -> float | None:
    value = record.get("overflow")
    if value is None:
        demand = record.get("demand")
        capacity = record.get("capacity")
        if demand is not None and capacity is not None:
            value = max(0.0, float(demand) - float(capacity))
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _accumulate_optional(item: dict[str, Any], key: str, value: float | None) -> None:
    if value is not None:
        item[key] = float(item.get(key) or 0.0) + value


def _demand_capacity_fields(item: dict[str, Any]) -> dict[str, float | None]:
    h_demand = _float_or_none(item.get("horizontal_demand"))
    v_demand = _float_or_none(item.get("vertical_demand"))
    h_capacity = _float_or_none(item.get("horizontal_capacity"))
    v_capacity = _float_or_none(item.get("vertical_capacity"))
    h_margin = None if h_demand is None or h_capacity is None else h_demand - h_capacity
    v_margin = None if v_demand is None or v_capacity is None else v_demand - v_capacity
    return {
        "horizontal_demand": h_demand,
        "vertical_demand": v_demand,
        "horizontal_capacity": h_capacity,
        "vertical_capacity": v_capacity,
        "horizontal_demand_capacity": h_margin,
        "vertical_demand_capacity": v_margin,
        "union_demand_capacity": max(value for value in (h_margin, v_margin) if value is not None) if h_margin is not None or v_margin is not None else None,
        "horizontal_utilization": _safe_ratio(h_demand, h_capacity),
        "vertical_utilization": _safe_ratio(v_demand, v_capacity),
    }


def _safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None
