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
        item = patch_totals[patch_id]
        layer = str(record.get("layer") or record.get("layer_name") or "unknown")
        layer_item = item["by_layer"].setdefault(layer, {"horizontal": 0.0, "vertical": 0.0})
        if direction == "vertical":
            item["vertical_overflow"] += overflow
            layer_item["vertical"] += overflow
        else:
            item["horizontal_overflow"] += overflow
            layer_item["horizontal"] += overflow
    labels = []
    for item in patch_totals.values():
        h = float(item["horizontal_overflow"])
        v = float(item["vertical_overflow"])
        labels.append({**item, "union_overflow": max(h, v)})
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
