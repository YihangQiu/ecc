from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def parse_sta_artifacts(stage_dir: Path) -> dict[str, Any]:
    """Parse ECC STA JSON and wire path artifacts into vector-ready records."""
    rpt_path = stage_dir / "data" / "sta" / "gcd.rpt.json"
    rpt = _read_json(rpt_path)
    summaries = rpt.get("summary", []) if isinstance(rpt.get("summary"), list) else []
    details = rpt.get("detail", []) if isinstance(rpt.get("detail"), list) else []
    slack = rpt.get("slack", []) if isinstance(rpt.get("slack"), list) else []
    wire_paths = sorted((stage_dir / "data" / "sta" / "wire_paths").glob("*.json"))
    records: list[dict[str, Any]] = []
    for idx, item in enumerate(summaries):
        if not isinstance(item, dict):
            continue
        detail = details[idx] if idx < len(details) and isinstance(details[idx], dict) else {}
        wire_path = wire_paths[idx] if idx < len(wire_paths) else None
        electrical = parse_wire_path(wire_path) if wire_path else {"summary": _empty_electrical(), "nodes": []}
        arc_sequence = _arc_sequence(detail.get("detail")) or _node_arc_sequence(electrical["nodes"])
        records.append(
            {
                "endpoint": item.get("endpoint"),
                "clock_group": item.get("clock_group") or detail.get("clock_field"),
                "delay_type": item.get("delay_type") or detail.get("type"),
                "path_delay": _to_float(item.get("path_delay")),
                "path_required": _to_float(item.get("path_required")),
                "cppr": _to_float(item.get("cppr")),
                "slack": _to_float(item.get("slack") if item.get("slack") is not None else detail.get("slack")),
                "freq": _to_float(item.get("freq")),
                "start_point": detail.get("start_point"),
                "arc_sequence": arc_sequence,
                "wire_electrical": electrical["summary"],
                "wire_path_nodes": electrical["nodes"],
                "source": str(rpt_path),
                "wire_path_source": str(wire_path) if wire_path else None,
                "null_reason": {} if wire_path else {"wire_path_source": "missing_wire_path_artifact"},
            }
        )
    return {
        "available": bool(records or slack),
        "records": records,
        "slack": slack,
        "source": str(rpt_path),
        "wire_path_sources": [str(path) for path in wire_paths],
    }


def parse_wire_path(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {"summary": _empty_electrical(), "nodes": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {"summary": _empty_electrical(), "nodes": []}
    nodes: list[dict[str, Any]] = []
    capacitance: list[float] = []
    slew: list[float] = []
    resistance: list[float] = []
    incr: list[float] = []
    if isinstance(payload, list):
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            for key, value in entry.items():
                if not isinstance(value, dict):
                    continue
                if key.startswith("node_"):
                    cap = _to_float(value.get("Capacitance"))
                    node_slew = _to_float(value.get("slew"))
                    if cap is not None:
                        capacitance.append(cap)
                    if node_slew is not None:
                        slew.append(node_slew)
                    nodes.append(
                        {
                            "id": key,
                            "point": value.get("Point"),
                            "capacitance": cap,
                            "slew": node_slew,
                            "trans_type": value.get("trans_type"),
                        }
                    )
                else:
                    inc = _to_float(value.get("Incr"))
                    res = _to_float(value.get("Resistance") or value.get("R"))
                    if inc is not None:
                        incr.append(inc)
                    if res is not None:
                        resistance.append(res)
    summary = {
        "capacitance_sum": sum(capacitance) if capacitance else None,
        "capacitance_list": capacitance,
        "max_slew": max(slew) if slew else None,
        "slew_list": slew,
        "resistance_sum": sum(resistance) if resistance else None,
        "resistance_list": resistance,
        "incr_delay_sum": sum(incr) if incr else None,
        "incr_delay_list": incr,
    }
    return {"summary": summary, "nodes": nodes}


def _arc_sequence(detail: Any) -> list[dict[str, Any]]:
    if not isinstance(detail, list):
        return []
    arcs = []
    for idx, item in enumerate(detail):
        if not isinstance(item, dict):
            continue
        arcs.append(
            {
                "id": idx,
                "name": item.get("name"),
                "incr_delay": _to_float(item.get("incr_delay")),
                "path_delay": _to_float(item.get("path_delay")),
            }
        )
    return arcs


def _node_arc_sequence(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"id": idx, "name": node.get("point"), "incr_delay": None, "path_delay": None} for idx, node in enumerate(nodes)]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _empty_electrical() -> dict[str, Any]:
    return {
        "capacitance_sum": None,
        "capacitance_list": [],
        "max_slew": None,
        "slew_list": [],
        "resistance_sum": None,
        "resistance_list": [],
        "incr_delay_sum": None,
        "incr_delay_list": [],
    }


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value))
    return float(match.group(0)) if match else None
