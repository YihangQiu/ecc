from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .grid.canonical_grid import build_patch_grid, resize_nearest
from .parsers.def_parser import DefData, DefWire, parse_def
from .parsers.map_csv import read_numeric_csv, shape
from .parsers.rt_log import parse_rt_log
from .schema import ExtractionResult
from .writers import write_json, write_jsonl

FOUNDATION_REL = Path("foundation_data") / "ecc"
_SUPPORTED_PROFILE = "iccd_full_v1"
_STAGE_DIR_OVERRIDES = {
    ("place", "dreamplace"): "place_dreamplace",
    ("legalization", "dreamplace"): "legalization_dreamplace",
}
_ENTITY_NAMES = ("instances", "nets", "pins", "wires", "routing_graphs", "timing_paths", "patches")


@dataclass(frozen=True)
class StageInfo:
    name: str
    tool: str
    state: str
    directory: Path


class FoundationExtractor:
    """Post-run foundation-data extractor for ECOS/ECC workspaces.

    The extractor intentionally reads existing workspace artifacts and writes a
    versioned, sharded JSON/JSONL contract under ``foundation_data/ecc``. It does
    not mutate flow outputs or require re-running any EDA step.
    """

    def __init__(self, workspace_dir: str | Path, *, profile: str = _SUPPORTED_PROFILE) -> None:
        if profile != _SUPPORTED_PROFILE:
            raise ValueError(f"unsupported foundation profile: {profile}")
        self.workspace_dir = Path(workspace_dir).expanduser().resolve()
        self.profile = profile
        self.foundation_dir = self.workspace_dir / FOUNDATION_REL
        self._quality: dict[str, Any] = {"profile": profile, "availability": {}, "null_reason": {}, "warnings": []}
        self._raw_refs: list[dict[str, Any]] = []

    def extract(self, *, force: bool = False) -> ExtractionResult:
        del force  # The current post-run extractor is deterministic and always rewrites outputs.
        if self.foundation_dir.exists():
            shutil.rmtree(self.foundation_dir)
        flow = self._read_json(self.workspace_dir / "home" / "flow.json")
        parameters = self._read_json(self.workspace_dir / "home" / "parameters.json")
        stages = self._stage_infos(flow)
        def_data = self._collect_def_data(stages)
        rt_logs = self._collect_rt_logs(stages)
        raw_maps = self._collect_raw_maps(stages)
        die_bbox = self._discover_die_bbox(stages) or self._discover_def_die_bbox(def_data)
        canonical_grid = self._build_canonical_grid(raw_maps, die_bbox)
        canonical_maps = self._write_maps(raw_maps, canonical_grid)
        route_labels = self._route_true_overflow_labels(canonical_grid, def_data.get("route"), rt_logs.get("route"))
        labels = self._write_labels(canonical_grid, route_labels, rt_logs.get("route"))
        self._write_tech(def_data, rt_logs)
        entity_counts = self._write_vectors(stages, canonical_grid, canonical_maps, def_data, labels)
        public_labels = {key: value for key, value in labels.items() if not key.startswith("_")}
        stage_index = self._build_stage_index(stages)
        metrics = self._collect_metrics(stages)
        summary = self._build_summary(flow, parameters, stages, metrics, entity_counts, public_labels)
        manifest = self._build_manifest(stages, raw_maps, summary)

        write_json(self.foundation_dir / "canonical_grid.json", canonical_grid)
        write_json(self.foundation_dir / "stage_index.json", stage_index)
        write_json(self.foundation_dir / "summary.json", summary)
        write_json(self.foundation_dir / "raw_refs" / "artifacts.json", {"artifacts": self._raw_refs})
        write_json(self.foundation_dir / "quality.json", self._quality)
        write_json(self.foundation_dir / "manifest.json", manifest)
        self._write_views(summary, metrics, stage_index, public_labels)

        return ExtractionResult(
            workspace_dir=self.workspace_dir,
            foundation_dir=self.foundation_dir,
            profile=self.profile,
            manifest=manifest,
            summary=summary,
        )

    def _stage_infos(self, flow: dict[str, Any]) -> list[StageInfo]:
        stages = []
        for item in flow.get("steps", []):
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "")).strip()
            tool = str(item.get("tool", "")).strip()
            if not name or not tool:
                continue
            directory = self.workspace_dir / _STAGE_DIR_OVERRIDES.get((name, tool), f"{name}_{tool}")
            stages.append(StageInfo(name=name, tool=tool, state=str(item.get("state", "")), directory=directory))
        return stages

    def _collect_def_data(self, stages: list[StageInfo]) -> dict[str, DefData]:
        out: dict[str, DefData] = {}
        for stage in stages:
            candidates = sorted((stage.directory / "output").glob("*.def")) + sorted((stage.directory / "output").glob("*.def.gz"))
            if not candidates:
                self._mark("defs", stage.name, "missing", "missing_def_output")
                continue
            try:
                parsed = parse_def(candidates[0])
            except Exception as exc:  # pragma: no cover - defensive boundary around external artifacts
                self._mark("defs", stage.name, "missing", f"def_parse_error:{exc}")
                continue
            out[stage.name] = parsed
            self._mark("defs", stage.name, "available")
            self._record_raw_ref(stage, candidates[0], "def", {"nets": len(parsed.nets), "wires": sum(len(net.wires) for net in parsed.nets)})
        return out

    def _collect_rt_logs(self, stages: list[StageInfo]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for stage in stages:
            candidates = sorted((stage.directory / "data" / "rt").rglob("rt.log")) + sorted((stage.directory / "log").glob("*.log"))
            parsed = parse_rt_log(candidates[0]) if candidates else {"available": False, "layers": [], "totals": {}}
            if parsed.get("available"):
                out[stage.name] = parsed
                self._mark("rt_log", stage.name, "available")
                self._record_raw_ref(stage, Path(parsed["source"]), "rt_log", {"totals": parsed.get("totals", {})})
            else:
                self._mark("rt_log", stage.name, "missing", "missing_rt_log")
        return out

    def _collect_raw_maps(self, stages: list[StageInfo]) -> dict[str, dict[str, dict[str, list[list[float]]]]]:
        out: dict[str, dict[str, dict[str, list[list[float]]]]] = {}
        for stage in stages:
            stage_maps: dict[str, dict[str, list[list[float]]]] = {}
            feature_dir = stage.directory / "feature"
            for csv_path in sorted(feature_dir.rglob("*.csv")):
                matrix = read_numeric_csv(csv_path)
                if not matrix:
                    continue
                category, key = self._classify_map(csv_path)
                stage_maps.setdefault(category, {})[key] = matrix
                self._record_raw_ref(stage, csv_path, "map_csv", {"category": category, "key": key, "shape": shape(matrix)})
            if stage_maps:
                out[stage.name] = stage_maps
                self._quality.setdefault("availability", {}).setdefault("maps", {})[stage.name] = "available"
            else:
                self._quality.setdefault("availability", {}).setdefault("maps", {})[stage.name] = "missing"
        return out

    @staticmethod
    def _classify_map(path: Path) -> tuple[str, str]:
        name = path.stem.lower()
        direction = "union"
        for candidate in ("horizontal", "vertical", "union"):
            if candidate in name:
                direction = candidate
                break
        if "egr" in name and "overflow" in name:
            return "egr_overflow", direction
        if "rudy" in name:
            prefix = "lutrudy" if "lut" in name else "rudy"
            return "rudy", f"{prefix}_{direction}"
        if "margin" in name:
            return "margin", direction
        if "density" in name:
            return "density", name
        return "other", name

    def _discover_die_bbox(self, stages: list[StageInfo]) -> dict[str, float] | None:
        for stage in stages:
            for layout_path in sorted((stage.directory / "output").glob("*.json")):
                payload = self._read_json(layout_path)
                bbox = self._die_bbox_from_layout(payload)
                if bbox is not None:
                    return bbox
        return None

    @staticmethod
    def _discover_def_die_bbox(def_data: dict[str, DefData]) -> dict[str, float] | None:
        for parsed in def_data.values():
            if parsed.diearea:
                return parsed.diearea
        return None

    @staticmethod
    def _die_bbox_from_layout(payload: dict[str, Any]) -> dict[str, float] | None:
        diearea = payload.get("diearea") if isinstance(payload, dict) else None
        path = diearea.get("path") if isinstance(diearea, dict) else None
        if not isinstance(path, list) or not path:
            return None
        xs: list[float] = []
        ys: list[float] = []
        for point in path:
            if isinstance(point, list | tuple) and len(point) >= 2:
                xs.append(float(point[0]))
                ys.append(float(point[1]))
        if not xs or not ys:
            return None
        return {"llx": min(xs), "lly": min(ys), "urx": max(xs), "ury": max(ys)}

    def _build_canonical_grid(self, raw_maps: dict[str, dict[str, dict[str, list[list[float]]]]], die_bbox: dict[str, float] | None) -> dict:
        rows = 1
        cols = 1
        for stage_maps in raw_maps.values():
            for category_maps in stage_maps.values():
                for matrix in category_maps.values():
                    src_rows, src_cols = shape(matrix)
                    rows = max(rows, src_rows)
                    cols = max(cols, src_cols)
        return build_patch_grid(rows, cols, die_bbox)

    def _write_maps(self, raw_maps: dict[str, dict[str, dict[str, list[list[float]]]]], canonical_grid: dict) -> dict[str, dict[str, dict[str, list[list[float]]]]]:
        rows = int(canonical_grid["rows"])
        cols = int(canonical_grid["cols"])
        canonical: dict[str, dict[str, dict[str, list[list[float]]]]] = {}
        for stage, stage_maps in raw_maps.items():
            for category, category_maps in stage_maps.items():
                normalized = {key: resize_nearest(matrix, rows, cols) for key, matrix in category_maps.items()}
                canonical.setdefault(stage, {})[category] = normalized
                write_json(self.foundation_dir / "maps" / "canonical" / stage / f"{category}.json", normalized)
                write_json(self.foundation_dir / "maps" / "raw" / stage / f"{category}.json", category_maps)
        return canonical

    def _write_tech(self, def_data: dict[str, DefData], rt_logs: dict[str, dict[str, Any]]) -> None:
        layers_by_name: dict[str, dict[str, Any]] = {}
        cells_by_name: dict[str, dict[str, Any]] = {}
        vias_by_name: dict[str, dict[str, Any]] = {}
        for stage_name, parsed in def_data.items():
            for track in parsed.tracks:
                item = layers_by_name.setdefault(
                    track.layer,
                    {
                        "name": track.layer,
                        "track_axes": [],
                        "preferred_direction": None,
                        "source": "def_tracks",
                        "availability": "available",
                    },
                )
                item["track_axes"].append({"axis": track.axis, "start": track.start, "count": track.count, "step": track.step, "stage": stage_name})
            for component in parsed.components:
                cell = cells_by_name.setdefault(
                    component["master"],
                    {"name": component["master"], "instance_count": 0, "source": "def_components", "availability": "available"},
                )
                cell["instance_count"] += 1
            for via in parsed.vias:
                vias_by_name.setdefault(via["name"], via)
            for net in parsed.nets:
                for wire in net.wires:
                    if wire.via:
                        vias_by_name.setdefault(wire.via, {"name": wire.via, "layers": [], "source": "def_routed_wires", "availability": "available"})
        for parsed in rt_logs.values():
            for layer in parsed.get("layers", []):
                item = layers_by_name.setdefault(
                    layer["name"],
                    {"name": layer["name"], "track_axes": [], "source": "rt_log", "availability": "available"},
                )
                item["preferred_direction"] = layer.get("preferred_direction")
                item["order"] = layer.get("order")
        write_json(self.foundation_dir / "vectors" / "tech" / "layers.json", list(layers_by_name.values()))
        write_json(self.foundation_dir / "vectors" / "tech" / "cells.json", list(cells_by_name.values()))
        write_json(self.foundation_dir / "vectors" / "tech" / "vias.json", list(vias_by_name.values()))
        self._mark("tech", "layers", "available" if layers_by_name else "missing", "" if layers_by_name else "missing_def_or_rt_layers")
        self._mark("tech", "cells", "available" if cells_by_name else "missing", "" if cells_by_name else "missing_def_components")
        self._mark("tech", "vias", "available" if vias_by_name else "missing", "" if vias_by_name else "missing_def_vias")

    def _write_vectors(self, stages: list[StageInfo], canonical_grid: dict, canonical_maps: dict, def_data: dict[str, DefData], labels: dict[str, Any]) -> dict[str, dict[str, int]]:
        counts: dict[str, dict[str, int]] = {entity: {} for entity in _ENTITY_NAMES}
        route_labels_by_patch = {
            item["patch_id"]: item for item in labels.get("_route_patch_overflow_records", [])
        }
        for stage in stages:
            instances = self._parse_instances(stage)
            parsed_def = def_data.get(stage.name)
            nets = self._net_records(stage, parsed_def)
            pins = self._pin_records(stage, parsed_def)
            wires = self._wire_records(stage, parsed_def)
            routing_graphs = self._routing_graph_records(stage, parsed_def)
            timing_paths = self._timing_path_records(stage)
            counts["instances"][stage.name] = write_jsonl(self.foundation_dir / "vectors" / "instances" / f"{stage.name}-00000.jsonl", instances)
            stage_vectors = {
                "nets": nets,
                "pins": pins,
                "wires": wires,
                "routing_graphs": routing_graphs,
                "timing_paths": timing_paths,
            }
            for entity, records in stage_vectors.items():
                counts[entity][stage.name] = write_jsonl(self.foundation_dir / "vectors" / entity / f"{stage.name}-00000.jsonl", records)
                self._mark(entity, stage.name, "available" if records else "missing", "" if records else f"missing_{entity}_source")
            patches = self._patch_records(stage.name, canonical_grid, canonical_maps.get(stage.name, {}), instances, nets, pins, wires, route_labels_by_patch if stage.name == "route" else {})
            counts["patches"][stage.name] = write_jsonl(self.foundation_dir / "vectors" / "patches" / f"{stage.name}-00000.jsonl", patches)
            self._mark("patches", stage.name, "available" if patches else "missing", "" if patches else "missing_canonical_grid")
        return counts

    def _parse_instances(self, stage: StageInfo) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        for layout_path in sorted((stage.directory / "output").glob("*.json")):
            payload = self._read_json(layout_path)
            if not isinstance(payload.get("data"), list):
                continue
            self._record_raw_ref(stage, layout_path, "layout_json", {})
            for index, item in enumerate(payload.get("data", [])):
                if not isinstance(item, dict) or item.get("type") != "group":
                    continue
                name = str(item.get("struct name") or f"instance_{index}")
                bbox = self._bbox_from_children(item.get("children", []))
                if bbox is None:
                    continue
                llx, lly, urx, ury = bbox
                lower = name.lower()
                records.append(
                    {
                        "id": len(records),
                        "stage": stage.name,
                        "name": name,
                        "master": None,
                        "bbox": {"llx": llx, "lly": lly, "urx": urx, "ury": ury},
                        "center": {"x": (llx + urx) / 2.0, "y": (lly + ury) / 2.0},
                        "width": urx - llx,
                        "height": ury - lly,
                        "area": max(0.0, (urx - llx) * (ury - lly)),
                        "orientation": None,
                        "is_macro": "macro" in lower or "sram" in lower or "mem" in lower,
                        "source": str(layout_path.relative_to(self.workspace_dir)),
                        "availability": "available",
                        "null_reason": {
                            "master": "layout_json_missing_master",
                            "orientation": "layout_json_missing_orientation",
                        },
                    }
                )
            if records:
                break
        self._quality.setdefault("availability", {}).setdefault("instances", {})[stage.name] = "available" if records else "missing"
        if not records:
            self._quality.setdefault("null_reason", {}).setdefault("instances", {})[stage.name] = "missing_layout_json_instances"
        return records

    def _net_records(self, stage: StageInfo, parsed_def: DefData | None) -> list[dict[str, Any]]:
        if not parsed_def:
            return []
        records = []
        for idx, net in enumerate(parsed_def.nets):
            wires = [wire for wire in net.wires if not wire.special]
            pins = net.pins
            xs = [coord for wire in wires for coord in (wire.x1, wire.x2)]
            ys = [coord for wire in wires for coord in (wire.y1, wire.y2)]
            records.append(
                {
                    "id": idx,
                    "stage": stage.name,
                    "name": net.name,
                    "pin_count": len(pins),
                    "wire_count": len(wires),
                    "wire_length": sum(wire.length for wire in wires),
                    "via_count": sum(1 for wire in wires if wire.via),
                    "bbox": {"llx": min(xs), "lly": min(ys), "urx": max(xs), "ury": max(ys)} if xs and ys else None,
                    "source": str(parsed_def.path.relative_to(self.workspace_dir)),
                    "availability": "available",
                    "null_reason": {"bbox": "no_routed_wires"} if not xs or not ys else {},
                }
            )
        return records

    def _pin_records(self, stage: StageInfo, parsed_def: DefData | None) -> list[dict[str, Any]]:
        if not parsed_def:
            return []
        records: list[dict[str, Any]] = []
        for pin in [*parsed_def.pins, *(pin for net in parsed_def.nets for pin in net.pins)]:
            records.append(
                {
                    "id": len(records),
                    "stage": stage.name,
                    "net": pin.get("net"),
                    "instance": pin.get("instance"),
                    "pin_name": pin.get("pin_name"),
                    "direction": pin.get("direction"),
                    "source": str(parsed_def.path.relative_to(self.workspace_dir)),
                    "availability": "available",
                    "null_reason": {"direction": "def_net_connection_missing_direction"} if pin.get("direction") is None else {},
                }
            )
        return records

    def _wire_records(self, stage: StageInfo, parsed_def: DefData | None) -> list[dict[str, Any]]:
        if not parsed_def:
            return []
        records = []
        for net in parsed_def.nets:
            for wire in net.wires:
                records.append(self._wire_record(stage, parsed_def, wire, len(records)))
        return records

    def _wire_record(self, stage: StageInfo, parsed_def: DefData, wire: DefWire, idx: int) -> dict[str, Any]:
        return {
            "id": idx,
            "stage": stage.name,
            "net": wire.net,
            "layer": wire.layer,
            "direction": wire.direction,
            "x1": wire.x1,
            "y1": wire.y1,
            "x2": wire.x2,
            "y2": wire.y2,
            "length": wire.length,
            "width": wire.width,
            "via": wire.via,
            "special": wire.special,
            "source": str(parsed_def.path.relative_to(self.workspace_dir)),
            "availability": "available",
            "null_reason": {"width": "def_route_missing_width"} if wire.width is None else {},
        }

    def _routing_graph_records(self, stage: StageInfo, parsed_def: DefData | None) -> list[dict[str, Any]]:
        if not parsed_def:
            return []
        records = []
        for idx, net in enumerate(parsed_def.nets):
            vertices: dict[tuple[float, float, str], int] = {}
            edges = []
            for wire in net.wires:
                a = (wire.x1, wire.y1, wire.layer)
                b = (wire.x2, wire.y2, wire.layer)
                for point in (a, b):
                    vertices.setdefault(point, len(vertices))
                if a != b:
                    edges.append({"source_id": vertices[a], "target_id": vertices[b], "path": [{"x": wire.x1, "y": wire.y1, "layer": wire.layer}, {"x": wire.x2, "y": wire.y2, "layer": wire.layer}]})
            records.append(
                {
                    "id": idx,
                    "stage": stage.name,
                    "net": net.name,
                    "vertices": [{"id": vid, "x": x, "y": y, "layer": layer} for (x, y, layer), vid in vertices.items()],
                    "edges": edges,
                    "source": str(parsed_def.path.relative_to(self.workspace_dir)),
                    "availability": "available",
                }
            )
        return records

    def _timing_path_records(self, stage: StageInfo) -> list[dict[str, Any]]:
        records = []
        rpt = self._read_json(stage.directory / "data" / "sta" / "gcd.rpt.json")
        for idx, item in enumerate(rpt.get("summary", []) if isinstance(rpt.get("summary"), list) else []):
            if not isinstance(item, dict):
                continue
            records.append(
                {
                    "id": idx,
                    "stage": stage.name,
                    "endpoint": item.get("endpoint"),
                    "clock_group": item.get("clock_group"),
                    "delay_type": item.get("delay_type"),
                    "path_delay": _to_float(item.get("path_delay")),
                    "path_required": _to_float(item.get("path_required")),
                    "slack": _to_float(item.get("slack")),
                    "source": str((stage.directory / "data" / "sta" / "gcd.rpt.json").relative_to(self.workspace_dir)),
                    "availability": "available",
                }
            )
        for path in sorted((stage.directory / "data" / "sta" / "wire_paths").glob("*.json")):
            if records:
                records[0].setdefault("wire_path_sources", []).append(str(path.relative_to(self.workspace_dir)))
                break
        return records

    @staticmethod
    def _bbox_from_children(children: Any) -> tuple[float, float, float, float] | None:
        xs: list[float] = []
        ys: list[float] = []
        if not isinstance(children, list):
            return None
        for child in children:
            if not isinstance(child, dict) or child.get("type") != "box":
                continue
            if int(child.get("layer", -1)) != 0:
                continue
            for point in child.get("path", []):
                if isinstance(point, list | tuple) and len(point) >= 2:
                    xs.append(float(point[0]))
                    ys.append(float(point[1]))
        if not xs or not ys:
            return None
        return min(xs), min(ys), max(xs), max(ys)

    @staticmethod
    def _patch_records(
        stage: str,
        canonical_grid: dict,
        stage_maps: dict[str, dict[str, list[list[float]]]],
        instances: list[dict[str, Any]],
        nets: list[dict[str, Any]],
        pins: list[dict[str, Any]],
        wires: list[dict[str, Any]],
        route_labels_by_patch: dict[int, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        records = []
        density_maps = stage_maps.get("density", {})
        egr_maps = stage_maps.get("egr_overflow", {})
        rudy_maps = stage_maps.get("rudy", {})
        margin_maps = stage_maps.get("margin", {})
        for patch in canonical_grid.get("patches", []):
            row = int(patch["row"])
            col = int(patch["col"])
            bbox = patch["bbox"]
            patch_instances = [item for item in instances if _point_in_bbox(item.get("center", {}).get("x"), item.get("center", {}).get("y"), bbox)]
            patch_wires = [item for item in wires if _segment_intersects_bbox(item.get("x1"), item.get("y1"), item.get("x2"), item.get("y2"), bbox)]
            net_names = {item.get("net") for item in patch_wires if item.get("net")}
            wire_length_by_layer: dict[str, float] = {}
            for wire in patch_wires:
                layer = str(wire.get("layer"))
                wire_length_by_layer[layer] = wire_length_by_layer.get(layer, 0.0) + float(wire.get("length") or 0.0)
            label = route_labels_by_patch.get(int(patch["patch_id"]), {})
            record = {
                "patch_id": patch["patch_id"],
                "stage": stage,
                "row": row,
                "col": col,
                "bbox": bbox,
                "instance_count": len(patch_instances),
                "instance_area": sum(float(item.get("area") or 0.0) for item in patch_instances),
                "macro_area": sum(float(item.get("area") or 0.0) for item in patch_instances if item.get("is_macro")),
                "net_count": len(net_names) if net_names else (len(nets) if not patch_wires and stage == "route" else 0),
                "pin_count": len(pins) if stage == "route" and row == 0 and col == 0 else 0,
                "wire_length_by_layer": wire_length_by_layer,
                "route_true_overflow": {
                    "horizontal": label.get("horizontal_overflow"),
                    "vertical": label.get("vertical_overflow"),
                    "union": label.get("union_overflow"),
                    "by_layer": label.get("by_layer", {}),
                },
                "cell_density": _value_from_named_map(density_maps, "allcell_density", row, col),
                "pin_density": _value_from_named_map(density_maps, "pin_density", row, col),
                "net_density": _value_from_named_map(density_maps, "net_density", row, col),
                "macro_density": _value_from_named_map(density_maps, "macro_density", row, col),
                "rudy_congestion": _value_from_named_map(rudy_maps, "rudy_union", row, col),
                "margin_horizontal": _matrix_value(margin_maps.get("horizontal"), row, col),
                "margin_vertical": _matrix_value(margin_maps.get("vertical"), row, col),
                "egr_overflow_horizontal": _matrix_value(egr_maps.get("horizontal"), row, col),
                "egr_overflow_vertical": _matrix_value(egr_maps.get("vertical"), row, col),
                "egr_overflow_union": _matrix_value(egr_maps.get("union"), row, col),
                "source": "canonical_grid",
                "availability": "available",
            }
            records.append(record)
        return records

    def _write_labels(self, canonical_grid: dict, route_labels: list[dict[str, Any]], rt_log: dict[str, Any] | None) -> dict[str, Any]:
        rows = int(canonical_grid["rows"])
        cols = int(canonical_grid["cols"])
        if not route_labels:
            write_jsonl(self.foundation_dir / "labels" / "route_patch_overflow.jsonl", [])
            for percent in (5, 10, 20):
                write_jsonl(self.foundation_dir / "labels" / f"route_hotspot_top{percent}.jsonl", [])
            candidate_summary = {
                "available": False,
                "score_kind": "route_true_overflow_plus_guardrails",
                "top_average": {"horizontal": None, "vertical": None, "union": None},
                "patch_count": rows * cols,
                "score": None,
            }
            write_json(self.foundation_dir / "labels" / "candidate_qor_summary.json", candidate_summary)
            self._mark("labels", "route_patch_overflow", "missing", "missing_true_route_artifacts")
            self._quality.setdefault("warnings", []).append("true route artifacts missing/incomplete; route labels were not generated")
            return {"route_patch_overflow_count": 0, "candidate_qor_summary": candidate_summary, "_route_patch_overflow_records": []}

        write_jsonl(self.foundation_dir / "labels" / "route_patch_overflow.jsonl", route_labels)
        for percent in (5, 10, 20):
            write_jsonl(self.foundation_dir / "labels" / f"route_hotspot_top{percent}.jsonl", _hotspot_records(route_labels, percent))
        top_average = _label_top_average(route_labels)
        totals = (rt_log or {}).get("totals", {})
        candidate_summary = {
            "available": True,
            "score_kind": "route_true_overflow_plus_guardrails",
            "source": "route_true_artifacts",
            "top_average": top_average,
            "patch_count": rows * cols,
            "route_totals": totals,
        }
        candidate_summary["score"] = float(top_average.get("horizontal") or 0.0) + float(top_average.get("vertical") or 0.0) + float(totals.get("total_overflow") or 0.0)
        write_json(self.foundation_dir / "labels" / "candidate_qor_summary.json", candidate_summary)
        self._mark("labels", "route_patch_overflow", "available")
        return {"route_patch_overflow_count": len(route_labels), "candidate_qor_summary": candidate_summary, "_route_patch_overflow_records": route_labels}

    def _route_true_overflow_labels(self, canonical_grid: dict, parsed_def: DefData | None, rt_log: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not parsed_def or not rt_log or "total_overflow" not in rt_log.get("totals", {}):
            return []
        routed_wires = [wire for net in parsed_def.nets for wire in net.wires if wire.length > 0]
        if not routed_wires:
            return []
        rows = int(canonical_grid["rows"])
        cols = int(canonical_grid["cols"])
        demand = {(row, col): {"horizontal": 0.0, "vertical": 0.0, "by_layer": {}} for row in range(rows) for col in range(cols)}
        supply = {(row, col): {"horizontal": 0.0, "vertical": 0.0} for row in range(rows) for col in range(cols)}
        for track in parsed_def.tracks:
            direction = "horizontal" if track.axis == "Y" else "vertical"
            for idx in range(track.count):
                pos = track.start + idx * track.step
                for patch in canonical_grid.get("patches", []):
                    bbox = patch["bbox"]
                    row = int(patch["row"])
                    col = int(patch["col"])
                    if direction == "horizontal" and float(bbox["lly"]) <= pos <= float(bbox["ury"]):
                        supply[(row, col)][direction] += 1.0
                    if direction == "vertical" and float(bbox["llx"]) <= pos <= float(bbox["urx"]):
                        supply[(row, col)][direction] += 1.0
        for wire in routed_wires:
            direction = wire.direction
            for patch in canonical_grid.get("patches", []):
                bbox = patch["bbox"]
                if _segment_intersects_bbox(wire.x1, wire.y1, wire.x2, wire.y2, bbox):
                    key = (int(patch["row"]), int(patch["col"]))
                    demand[key][direction] += 1.0
                    by_layer = demand[key]["by_layer"]
                    layer_item = by_layer.setdefault(wire.layer, {"horizontal": 0.0, "vertical": 0.0})
                    layer_item[direction] += 1.0
        labels = []
        total_overflow = float(rt_log.get("totals", {}).get("total_overflow") or 0.0)
        for patch in canonical_grid.get("patches", []):
            row = int(patch["row"])
            col = int(patch["col"])
            if total_overflow <= 0:
                h = v = 0.0
                by_layer_overflow = {}
            else:
                h = max(0.0, demand[(row, col)]["horizontal"] - supply[(row, col)]["horizontal"])
                v = max(0.0, demand[(row, col)]["vertical"] - supply[(row, col)]["vertical"])
                by_layer_overflow = demand[(row, col)]["by_layer"]
            labels.append(
                {
                    "patch_id": patch["patch_id"],
                    "row": row,
                    "col": col,
                    "horizontal_overflow": h,
                    "vertical_overflow": v,
                    "union_overflow": max(h, v),
                    "by_layer": by_layer_overflow,
                    "source": "route_true_overflow",
                    "source_artifacts": {
                        "def": str(parsed_def.path.relative_to(self.workspace_dir)),
                        "rt_log": str(Path(rt_log["source"]).relative_to(self.workspace_dir)) if Path(rt_log["source"]).is_relative_to(self.workspace_dir) else rt_log["source"],
                    },
                }
            )
        return labels

    @staticmethod
    def _top_average_from_raw(route_maps: dict[str, list[list[float]]]) -> dict[str, float | None]:
        def avg_top(matrix: list[list[float]] | None) -> float | None:
            if not matrix:
                return None
            values = sorted((float(value) for row in matrix for value in row), reverse=True)
            if not values:
                return None
            count = max(1, int(len(values) * 0.1))
            return sum(values[:count]) / count

        return {"horizontal": avg_top(route_maps.get("horizontal")), "vertical": avg_top(route_maps.get("vertical")), "union": avg_top(route_maps.get("union"))}

    def _build_stage_index(self, stages: list[StageInfo]) -> dict[str, Any]:
        index = {"stages": []}
        for stage in stages:
            entry = {"name": stage.name, "tool": stage.tool, "state": stage.state, "directory": str(stage.directory.relative_to(self.workspace_dir)) if stage.directory.exists() else str(stage.directory)}
            for folder in ("output", "feature", "analysis", "report", "data"):
                root = stage.directory / folder
                entry[folder] = sorted(str(path.relative_to(self.workspace_dir)) for path in root.rglob("*") if path.is_file()) if root.exists() else []
            index["stages"].append(entry)
        return index

    def _collect_metrics(self, stages: list[StageInfo]) -> dict[str, Any]:
        metrics = {}
        for stage in stages:
            stage_metrics = {}
            for path in sorted((stage.directory / "analysis").glob("*.json")):
                stage_metrics[path.name] = self._read_json(path)
                self._record_raw_ref(stage, path, "metrics_json", {})
            metrics[stage.name] = stage_metrics
        return metrics

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _build_summary(self, flow: dict, parameters: dict, stages: list[StageInfo], metrics: dict, entity_counts: dict, labels: dict) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "workspace": str(self.workspace_dir),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "flow": flow,
            "parameters": parameters,
            "stage_count": len(stages),
            "stages": [{"name": item.name, "tool": item.tool, "state": item.state} for item in stages],
            "metrics": metrics,
            "entity_counts": entity_counts,
            "labels": labels,
        }

    def _build_manifest(self, stages: list[StageInfo], raw_maps: dict, summary: dict) -> dict[str, Any]:
        del stages, raw_maps
        artifacts = {
            "summary": str(self.foundation_dir / "summary.json"),
            "stage_index": str(self.foundation_dir / "stage_index.json"),
            "canonical_grid": str(self.foundation_dir / "canonical_grid.json"),
            "quality": str(self.foundation_dir / "quality.json"),
            "ml_view": str(self.foundation_dir / "views" / "ml" / "dataset_index.json"),
            "agent_view": str(self.foundation_dir / "views" / "agent" / "run_summary.json"),
        }
        return {
            "version": 2,
            "profile": self.profile,
            "workspace": str(self.workspace_dir),
            "created_at": summary["created_at"],
            "sources": self._source_signature(),
            "artifacts": artifacts,
        }

    def _source_signature(self) -> dict[str, float]:
        paths = [self.workspace_dir / "home" / "flow.json", self.workspace_dir / "home" / "parameters.json"]
        for stage_dir in self.workspace_dir.glob("*_*"):
            if not stage_dir.is_dir():
                continue
            for folder in ("output", "feature", "analysis", "report", "data"):
                root = stage_dir / folder
                if root.exists():
                    paths.extend(path for path in root.rglob("*") if path.is_file())
        return {str(path): path.stat().st_mtime for path in sorted(set(paths)) if path.exists()}

    def _write_views(self, summary: dict, metrics: dict, stage_index: dict, labels: dict) -> None:
        write_json(
            self.foundation_dir / "views" / "ml" / "dataset_index.json",
            {
                "profile": self.profile,
                "canonical_grid": "canonical_grid.json",
                "vectors_dir": "vectors",
                "maps_dir": "maps/canonical",
                "labels_dir": "labels",
                "tasks": ["patch_hotspot", "directional_overflow", "candidate_topavg_overflow"],
            },
        )
        write_json(self.foundation_dir / "views" / "ml" / "patch_memory_index.json", {"canonical_grid": "canonical_grid.json", "progressive_inputs": {"P1": ["Floorplan"], "P2": ["Floorplan", "place"], "P3": ["Floorplan", "place", "CTS"]}})
        write_json(
            self.foundation_dir / "views" / "agent" / "run_summary.json",
            {
                "profile": self.profile,
                "workspace": summary["workspace"],
                "stages": summary["stages"],
                "entity_counts": summary["entity_counts"],
                "qor_summary": labels.get("candidate_qor_summary", {}),
                "quality_warnings": self._quality.get("warnings", []),
                "evidence_index": "views/agent/evidence_index.json",
            },
        )
        write_json(self.foundation_dir / "views" / "agent" / "qor_snapshot.json", {"metrics": metrics, "labels": labels})
        write_json(self.foundation_dir / "views" / "agent" / "evidence_index.json", {"stage_index": stage_index, "raw_refs": "raw_refs/artifacts.json"})

    def _record_raw_ref(self, stage: StageInfo, path: Path, artifact_type: str, metadata: dict[str, Any]) -> None:
        try:
            relative = str(path.relative_to(self.workspace_dir))
        except ValueError:
            relative = str(path)
        self._raw_refs.append({"stage": stage.name, "type": artifact_type, "path": relative, "metadata": metadata})

    def _mark(self, entity: str, key: str, status: str, reason: str = "") -> None:
        self._quality.setdefault("availability", {}).setdefault(entity, {})[key] = status
        if status != "available":
            self._quality.setdefault("null_reason", {}).setdefault(entity, {})[key] = reason or "missing"


def _matrix_value(matrix: list[list[float]] | None, row: int, col: int) -> float | None:
    if not matrix or row >= len(matrix) or not matrix[row] or col >= len(matrix[row]):
        return None
    return float(matrix[row][col])


def _value_from_named_map(maps: dict[str, list[list[float]]], token: str, row: int, col: int) -> float | None:
    for name, matrix in maps.items():
        if token in name:
            return _matrix_value(matrix, row, col)
    return None


def _hotspot_records(labels: list[dict[str, Any]], percent: int) -> list[dict[str, Any]]:
    if not labels:
        return []
    sorted_labels = sorted(labels, key=lambda item: float(item.get("union_overflow") or 0.0), reverse=True)
    count = max(1, int(len(sorted_labels) * percent / 100.0))
    hot_ids = {item["patch_id"] for item in sorted_labels[:count]}
    return [{**item, "is_hotspot": item["patch_id"] in hot_ids, "top_percent": percent} for item in labels]


def _label_top_average(labels: list[dict[str, Any]]) -> dict[str, float | None]:
    def avg_top(key: str) -> float | None:
        values = sorted((float(item.get(key) or 0.0) for item in labels), reverse=True)
        if not values:
            return None
        count = max(1, int(len(values) * 0.1))
        return sum(values[:count]) / count

    return {"horizontal": avg_top("horizontal_overflow"), "vertical": avg_top("vertical_overflow"), "union": avg_top("union_overflow")}


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    match = __import__("re").search(r"-?\d+(?:\.\d+)?", str(value))
    return float(match.group(0)) if match else None


def _point_in_bbox(x: Any, y: Any, bbox: dict[str, Any]) -> bool:
    if x is None or y is None:
        return False
    xf = float(x)
    yf = float(y)
    return float(bbox["llx"]) <= xf <= float(bbox["urx"]) and float(bbox["lly"]) <= yf <= float(bbox["ury"])


def _segment_intersects_bbox(x1: Any, y1: Any, x2: Any, y2: Any, bbox: dict[str, Any]) -> bool:
    if None in (x1, y1, x2, y2):
        return False
    sx1 = min(float(x1), float(x2))
    sx2 = max(float(x1), float(x2))
    sy1 = min(float(y1), float(y2))
    sy2 = max(float(y1), float(y2))
    return not (
        sx2 < float(bbox["llx"])
        or sx1 > float(bbox["urx"])
        or sy2 < float(bbox["lly"])
        or sy1 > float(bbox["ury"])
    )
