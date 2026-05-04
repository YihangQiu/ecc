from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .grid.canonical_grid import build_gcell_patch_grid, build_patch_grid, resize_nearest
from .parsers.def_parser import DefData, DefWire, parse_def
from .parsers.drc_parser import parse_drc_artifacts
from .parsers.gcell import parse_gcell_info
from .parsers.map_csv import read_numeric_csv, shape
from .parsers.route_native_demand_capacity import parse_route_native_demand_capacity_artifacts
from .parsers.rt_log import parse_rt_log
from .parsers.sta_parser import parse_sta_artifacts
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
        self._quality: dict[str, Any] = {"availability": {}, "null_reason": {}, "warnings": []}
        self._raw_refs: list[dict[str, Any]] = []
        self._exact_gcell_map_keys: set[tuple[str, str, str]] = set()

    def extract(self, *, force: bool = False, stages: Any = "all", include_raw_refs: bool = True) -> ExtractionResult:
        del force  # The current post-run extractor is deterministic and always rewrites outputs.
        if self.foundation_dir.exists():
            shutil.rmtree(self.foundation_dir)
        flow = self._read_json(self.workspace_dir / "home" / "flow.json")
        parameters = self._read_json(self.workspace_dir / "home" / "parameters.json")
        selected_stages = self._filter_stages(self._stage_infos(flow), stages)
        options = {"stages": [stage.name for stage in selected_stages], "include_raw_refs": bool(include_raw_refs)}
        def_data = self._collect_def_data(selected_stages)
        rt_logs = self._collect_rt_logs(selected_stages)
        sta_reports = self._collect_sta_reports(selected_stages)
        drc_reports = self._collect_drc_reports(selected_stages)
        raw_maps = self._collect_raw_maps(selected_stages)
        die_bbox = self._discover_die_bbox(selected_stages) or self._discover_def_die_bbox(def_data)
        canonical_grid = self._build_canonical_grid(raw_maps, die_bbox, selected_stages)
        canonical_maps = self._write_maps(raw_maps, canonical_grid, selected_stages, def_data)
        route_stage = next((stage for stage in selected_stages if stage.name == "route"), None)
        native_demand_capacity = parse_route_native_demand_capacity_artifacts(route_stage.directory, canonical_grid) if route_stage else {"available": False, "labels": []}
        reconstructed_congestion = self._route_reconstructed_congestion(canonical_grid, def_data.get("route"), rt_logs.get("route"))
        labels = self._write_labels(native_demand_capacity.get("labels", []), reconstructed_congestion)
        self._write_tech(def_data, rt_logs)
        entity_counts = self._write_vectors(selected_stages, canonical_grid, canonical_maps, def_data, labels, sta_reports, drc_reports)
        public_labels = {key: value for key, value in labels.items() if not key.startswith("_")}
        stage_index = self._build_stage_index(selected_stages)
        metrics = self._collect_metrics(selected_stages)
        summary_parameters = self._build_summary_parameters(parameters, selected_stages, def_data)
        summary = self._build_summary(flow, summary_parameters, selected_stages, metrics, entity_counts, public_labels, def_data, sta_reports, drc_reports)
        manifest = self._build_manifest(selected_stages, raw_maps, summary, options=options)

        write_json(self.foundation_dir / "canonical_grid.json", canonical_grid)
        write_json(self.foundation_dir / "stage_index.json", stage_index)
        write_json(self.foundation_dir / "summary.json", summary)
        if include_raw_refs:
            write_json(self.foundation_dir / "raw_refs" / "artifacts.json", {"artifacts": self._raw_refs})
        write_json(self.foundation_dir / "quality.json", self._quality)
        write_json(self.foundation_dir / "manifest.json", manifest)
        self._write_views(summary, metrics, stage_index, public_labels, include_raw_refs=bool(include_raw_refs))

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

    @staticmethod
    def _filter_stages(stages: list[StageInfo], requested: Any) -> list[StageInfo]:
        if requested is None:
            return stages
        if isinstance(requested, str):
            normalized = requested.strip()
            if not normalized or normalized.lower() == "all":
                return stages
            requested_names = [item.strip() for item in normalized.split(",") if item.strip()]
        elif isinstance(requested, list | tuple | set):
            requested_names = [str(item).strip() for item in requested if str(item).strip()]
        else:
            raise ValueError("stages must be 'all', a stage name, or a list of stage names")
        if not requested_names:
            return stages
        by_name = {stage.name: stage for stage in stages}
        unknown = [name for name in requested_names if name not in by_name]
        if unknown:
            raise ValueError(f"unknown foundation extraction stage: {', '.join(unknown)}")
        return [by_name[name] for name in requested_names]

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

    def _collect_sta_reports(self, stages: list[StageInfo]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for stage in stages:
            parsed = parse_sta_artifacts(stage.directory)
            if parsed.get("available"):
                out[stage.name] = parsed
                self._mark("sta", stage.name, "available")
                source = Path(str(parsed.get("source", "")))
                if source.exists():
                    self._record_raw_ref(stage, source, "sta_report_json", {"paths": len(parsed.get("records", []))})
                for wire_source in parsed.get("wire_path_sources", []):
                    wire_path = Path(str(wire_source))
                    if wire_path.exists():
                        self._record_raw_ref(stage, wire_path, "sta_wire_path", {})
            else:
                self._mark("sta", stage.name, "missing", "missing_sta_report")
        return out

    def _collect_drc_reports(self, stages: list[StageInfo]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for stage in stages:
            parsed = parse_drc_artifacts(stage.directory)
            if parsed.get("available"):
                out[stage.name] = parsed
                self._mark("drc", stage.name, "available")
                source = Path(str(parsed.get("source", "")))
                if source.exists():
                    self._record_raw_ref(stage, source, "drc_violation_map", {"count": parsed.get("count", 0)})
            else:
                self._mark("drc", stage.name, "missing", "missing_drc_artifacts")
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
                exact_gcell_map = "gcell_patch_map" in csv_path.parts
                if exact_gcell_map:
                    self._exact_gcell_map_keys.add((stage.name, category, key))
                if key in stage_maps.setdefault(category, {}) and not exact_gcell_map and (stage.name, category, key) in self._exact_gcell_map_keys:
                    continue
                stage_maps[category][key] = matrix
                self._record_raw_ref(
                    stage,
                    csv_path,
                    "gcell_patch_map_csv" if exact_gcell_map else "map_csv",
                    {"category": category, "key": key, "shape": shape(matrix), "grid_source": "irt_gcell_info" if exact_gcell_map else "tool_default"},
                )
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

    def _build_canonical_grid(self, raw_maps: dict[str, dict[str, dict[str, list[list[float]]]]], die_bbox: dict[str, float] | None, stages: list[StageInfo]) -> dict:
        gcell = self._discover_gcell_info(stages)
        if gcell:
            path, cells = gcell
            try:
                self._record_raw_ref(next(stage for stage in stages if path.is_relative_to(stage.directory)), path, "irt_gcell_info", {"cells": len(cells)})
            except (StopIteration, ValueError):
                pass
            self._mark("grid", "canonical", "available")
            return build_gcell_patch_grid(cells, source=str(path.relative_to(self.workspace_dir)) if path.is_relative_to(self.workspace_dir) else str(path))
        rows = 1
        cols = 1
        for stage_maps in raw_maps.values():
            for category_maps in stage_maps.values():
                for matrix in category_maps.values():
                    src_rows, src_cols = shape(matrix)
                    rows = max(rows, src_rows)
                    cols = max(cols, src_cols)
        self._mark("grid", "canonical", "available")
        return build_patch_grid(rows, cols, die_bbox)

    def _discover_gcell_info(self, stages: list[StageInfo]) -> tuple[Path, list[dict[str, Any]]] | None:
        candidates: list[Path] = []
        for preferred in ("route", "CTS", "place"):
            candidates.extend(
                stage.directory / "data" / "rt" / "rt_temp_directory" / "early_router" / "gcell.info"
                for stage in stages
                if stage.name == preferred
            )
        candidates.extend(stage.directory / "data" / "rt" / "rt_temp_directory" / "early_router" / "gcell.info" for stage in stages)
        for path in candidates:
            if not path.exists():
                continue
            cells = parse_gcell_info(path)
            if cells:
                return path, cells
        return None

    def _write_maps(
        self,
        raw_maps: dict[str, dict[str, dict[str, list[list[float]]]]],
        canonical_grid: dict,
        stages: list[StageInfo],
        def_data: dict[str, DefData],
    ) -> dict[str, dict[str, dict[str, list[list[float]]]]]:
        rows = int(canonical_grid["rows"])
        cols = int(canonical_grid["cols"])
        stages_by_name = {stage.name: stage for stage in stages}
        canonical: dict[str, dict[str, dict[str, list[list[float]]]]] = {}
        for stage, stage_maps in raw_maps.items():
            for category, category_maps in stage_maps.items():
                normalized = self._canonicalize_maps_for_grid(
                    category,
                    category_maps,
                    canonical_grid,
                    stages_by_name.get(stage),
                    def_data.get(stage),
                    rows,
                    cols,
                )
                canonical.setdefault(stage, {})[category] = normalized
                write_json(self.foundation_dir / "maps" / "canonical" / stage / f"{category}.json", normalized)
                write_json(self.foundation_dir / "maps" / "raw" / stage / f"{category}.json", category_maps)
        return canonical

    def _canonicalize_maps_for_grid(
        self,
        category: str,
        category_maps: dict[str, list[list[float]]],
        canonical_grid: dict,
        stage: StageInfo | None,
        parsed_def: DefData | None,
        rows: int,
        cols: int,
    ) -> dict[str, list[list[float]]]:
        if category == "egr_overflow":
            for key, matrix in category_maps.items():
                src_shape = shape(matrix)
                if src_shape != (rows, cols):
                    self._quality.setdefault("warnings", []).append(
                        f"egr map {stage.name if stage else 'unknown'}:{key} shape {src_shape} does not match canonical gcell grid {(rows, cols)}; kept raw without resize"
                    )
            return {key: [[float(value) for value in row] for row in matrix] for key, matrix in category_maps.items()}
        if canonical_grid.get("grid_source") == "irt_gcell_info" and stage is not None and category in {"density", "rudy", "margin"}:
            exact_maps = {
                key: [[float(value) for value in row] for row in matrix]
                for key, matrix in category_maps.items()
                if (stage.name, category, key) in self._exact_gcell_map_keys and shape(matrix) == (rows, cols)
            }
            missing_maps = {key: matrix for key, matrix in category_maps.items() if key not in exact_maps}
            if missing_maps:
                self._quality.setdefault("warnings", []).append(
                    f"exact ecc-tools gcell patch maps missing for {stage.name}:{category}:{sorted(missing_maps)}; omitted approximate Python recomputation"
                )
            return exact_maps
        return {key: resize_nearest(matrix, rows, cols) for key, matrix in category_maps.items()}

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
                    },
                )
                item["track_axes"].append({"axis": track.axis, "start": track.start, "count": track.count, "step": track.step, "stage": stage_name})
            for component in parsed.components:
                cell = cells_by_name.setdefault(
                    component["master"],
                    {"name": component["master"], "instance_count": 0, "source": "def_components"},
                )
                cell["instance_count"] += 1
            for via in parsed.vias:
                vias_by_name.setdefault(via["name"], via)
            for net in parsed.nets:
                for wire in net.wires:
                    if wire.via:
                        vias_by_name.setdefault(wire.via, {"name": wire.via, "layers": [], "source": "def_routed_wires"})
        for parsed in rt_logs.values():
            for layer in parsed.get("layers", []):
                item = layers_by_name.setdefault(
                    layer["name"],
                    {"name": layer["name"], "track_axes": [], "source": "rt_log"},
                )
                item["preferred_direction"] = layer.get("preferred_direction")
                item["order"] = layer.get("order")
        write_json(self.foundation_dir / "vectors" / "tech" / "layers.json", list(layers_by_name.values()))
        write_json(self.foundation_dir / "vectors" / "tech" / "cells.json", list(cells_by_name.values()))
        write_json(self.foundation_dir / "vectors" / "tech" / "vias.json", list(vias_by_name.values()))
        self._mark("tech", "layers", "available" if layers_by_name else "missing", "" if layers_by_name else "missing_def_or_rt_layers")
        self._mark("tech", "cells", "available" if cells_by_name else "missing", "" if cells_by_name else "missing_def_components")
        self._mark("tech", "vias", "available" if vias_by_name else "missing", "" if vias_by_name else "missing_def_vias")

    def _write_vectors(
        self,
        stages: list[StageInfo],
        canonical_grid: dict,
        canonical_maps: dict,
        def_data: dict[str, DefData],
        labels: dict[str, Any],
        sta_reports: dict[str, dict[str, Any]],
        drc_reports: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, int]]:
        counts: dict[str, dict[str, int]] = {entity: {} for entity in _ENTITY_NAMES}
        native_demand_capacity_by_patch = {
            item["patch_id"]: item for item in labels.get("_route_native_demand_capacity_records", [])
        }
        reconstructed_by_patch = {
            item["patch_id"]: item for item in labels.get("_route_reconstructed_congestion_records", [])
        }
        for stage in stages:
            instances = self._parse_instances(stage)
            parsed_def = def_data.get(stage.name)
            nets = self._net_records(stage, parsed_def)
            pins = self._pin_records(stage, parsed_def)
            wires = self._wire_records(stage, parsed_def)
            routing_graphs = self._routing_graph_records(stage, parsed_def)
            timing_paths = self._timing_path_records(stage, sta_reports.get(stage.name))
            counts["instances"][stage.name] = write_jsonl(self.foundation_dir / "vectors" / "instances" / f"{stage.name}.jsonl", instances)
            stage_vectors = {
                "nets": nets,
                "pins": pins,
                "wires": wires,
                "routing_graphs": routing_graphs,
                "timing_paths": timing_paths,
            }
            for entity, records in stage_vectors.items():
                counts[entity][stage.name] = write_jsonl(self.foundation_dir / "vectors" / entity / f"{stage.name}.jsonl", records)
                self._mark(entity, stage.name, "available" if records else "missing", "" if records else f"missing_{entity}_source")
            patches = self._patch_records(
                stage.name,
                canonical_grid,
                canonical_maps.get(stage.name, {}),
                instances,
                nets,
                pins,
                wires,
                native_demand_capacity_by_patch if stage.name == "route" else {},
                reconstructed_by_patch if stage.name == "route" else {},
                timing_paths,
                drc_reports.get(stage.name),
            )
            counts["patches"][stage.name] = write_jsonl(self.foundation_dir / "vectors" / "patches" / f"{stage.name}.jsonl", patches)
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
                }
            )
        return records

    def _timing_path_records(self, stage: StageInfo, sta_report: dict[str, Any] | None) -> list[dict[str, Any]]:
        if sta_report:
            records = []
            for idx, item in enumerate(sta_report.get("records", [])):
                record = {**item, "id": idx, "stage": stage.name}
                for key in ("source", "wire_path_source"):
                    value = record.get(key)
                    if value:
                        try:
                            record[key] = str(Path(str(value)).relative_to(self.workspace_dir))
                        except ValueError:
                            record[key] = str(value)
                records.append(record)
            return records
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
        native_demand_capacity_by_patch: dict[int, dict[str, Any]],
        reconstructed_by_patch: dict[int, dict[str, Any]],
        timing_paths: list[dict[str, Any]],
        drc_report: dict[str, Any] | None,
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
            native_demand_capacity = native_demand_capacity_by_patch.get(int(patch["patch_id"]), {})
            reconstructed = reconstructed_by_patch.get(int(patch["patch_id"]), {})
            patch_drc = _drc_for_patch(drc_report, bbox)
            record = {
                "patch_id": patch["patch_id"],
                "stage": stage,
                "row": row,
                "col": col,
                "instance_count": len(patch_instances),
                "instance_area": sum(float(item.get("area") or 0.0) for item in patch_instances),
                "macro_area": sum(float(item.get("area") or 0.0) for item in patch_instances if item.get("is_macro")),
                "net_count": len(net_names) if net_names else (len(nets) if not patch_wires and stage == "route" else 0),
                "pin_count": len(pins) if stage == "route" and row == 0 and col == 0 else 0,
                "wire_length_by_layer": wire_length_by_layer,
                "route_reconstructed_congestion": {
                    "horizontal": reconstructed.get("horizontal_overflow"),
                    "vertical": reconstructed.get("vertical_overflow"),
                    "union": reconstructed.get("union_overflow"),
                    "by_layer": reconstructed.get("by_layer", {}),
                },
                "route_native_demand_capacity": _demand_capacity_label(native_demand_capacity),
                "route_reconstructed_demand_capacity": _demand_capacity_label(reconstructed),
                "route_demand_capacity": _demand_capacity_label(_demand_capacity_source(native_demand_capacity, reconstructed)),
                "drc": patch_drc,
                "timing": _timing_for_patch(timing_paths),
                "electrical": _electrical_for_patch(timing_paths),
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
            }
            records.append(record)
        return records

    def _write_labels(
        self,
        native_demand_capacity: list[dict[str, Any]],
        reconstructed_congestion: list[dict[str, Any]],
    ) -> dict[str, Any]:
        write_jsonl(self.foundation_dir / "labels" / "route_native_demand_capacity.jsonl", native_demand_capacity)
        self._mark(
            "labels",
            "route_native_demand_capacity",
            "available" if native_demand_capacity else "missing",
            "" if native_demand_capacity else "missing_irt_space_router_native_demand_capacity_artifact",
        )
        write_jsonl(self.foundation_dir / "labels" / "route_reconstructed_congestion.jsonl", reconstructed_congestion)
        write_jsonl(self.foundation_dir / "labels" / "route_reconstructed_demand_capacity.jsonl", reconstructed_congestion)
        self._mark(
            "labels",
            "route_reconstructed_congestion",
            "available" if reconstructed_congestion else "missing",
            "" if reconstructed_congestion else "missing_routed_def_tracks_reconstruction_inputs",
        )
        self._mark(
            "labels",
            "route_reconstructed_demand_capacity",
            "available" if reconstructed_congestion else "missing",
            "" if reconstructed_congestion else "missing_routed_def_tracks_reconstruction_inputs",
        )
        return {
            "route_native_demand_capacity_count": len(native_demand_capacity),
            "route_reconstructed_demand_capacity_count": len(reconstructed_congestion),
            "route_reconstructed_congestion_count": len(reconstructed_congestion),
            "_route_native_demand_capacity_records": native_demand_capacity,
            "_route_reconstructed_congestion_records": reconstructed_congestion,
        }

    def _route_reconstructed_congestion(self, canonical_grid: dict, parsed_def: DefData | None, rt_log: dict[str, Any] | None) -> list[dict[str, Any]]:
        if not parsed_def or not rt_log or "total_overflow" not in rt_log.get("totals", {}):
            return []
        routed_wires = [wire for net in parsed_def.nets for wire in net.wires if wire.length > 0]
        if not routed_wires:
            return []
        rows = int(canonical_grid["rows"])
        cols = int(canonical_grid["cols"])
        demand = {(row, col): {"horizontal": 0.0, "vertical": 0.0, "by_layer": {}} for row in range(rows) for col in range(cols)}
        capacity = {(row, col): {"horizontal": 0.0, "vertical": 0.0} for row in range(rows) for col in range(cols)}
        for track in parsed_def.tracks:
            direction = "horizontal" if track.axis == "Y" else "vertical"
            for idx in range(track.count):
                pos = track.start + idx * track.step
                for patch in canonical_grid.get("patches", []):
                    bbox = patch["bbox"]
                    row = int(patch["row"])
                    col = int(patch["col"])
                    if direction == "horizontal" and float(bbox["lly"]) <= pos <= float(bbox["ury"]):
                        capacity[(row, col)][direction] += 1.0
                    if direction == "vertical" and float(bbox["llx"]) <= pos <= float(bbox["urx"]):
                        capacity[(row, col)][direction] += 1.0
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
                h = max(0.0, demand[(row, col)]["horizontal"] - capacity[(row, col)]["horizontal"])
                v = max(0.0, demand[(row, col)]["vertical"] - capacity[(row, col)]["vertical"])
                by_layer_overflow = demand[(row, col)]["by_layer"]
            horizontal_demand = demand[(row, col)]["horizontal"]
            vertical_demand = demand[(row, col)]["vertical"]
            horizontal_capacity = capacity[(row, col)]["horizontal"]
            vertical_capacity = capacity[(row, col)]["vertical"]
            horizontal_demand_capacity = horizontal_demand - horizontal_capacity
            vertical_demand_capacity = vertical_demand - vertical_capacity
            labels.append(
                {
                    "patch_id": patch["patch_id"],
                    "row": row,
                    "col": col,
                    "horizontal_demand": horizontal_demand,
                    "vertical_demand": vertical_demand,
                    "horizontal_capacity": horizontal_capacity,
                    "vertical_capacity": vertical_capacity,
                    "horizontal_demand_capacity": horizontal_demand_capacity,
                    "vertical_demand_capacity": vertical_demand_capacity,
                    "union_demand_capacity": max(horizontal_demand_capacity, vertical_demand_capacity),
                    "horizontal_utilization": _safe_ratio(horizontal_demand, horizontal_capacity),
                    "vertical_utilization": _safe_ratio(vertical_demand, vertical_capacity),
                    "horizontal_overflow": h,
                    "vertical_overflow": v,
                    "union_overflow": max(h, v),
                    "by_layer": by_layer_overflow,
                    "source": "routed_def_tracks_reconstruction",
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
            stage_metrics: dict[str, Any] = {}
            for path in sorted((stage.directory / "analysis").glob("*.json")):
                stage_metrics[path.name] = self._read_json(path)
                self._record_raw_ref(stage, path, "metrics_json", {})
            feature_metrics = self._collect_feature_metric_files(stage)
            if feature_metrics:
                stage_metrics["features"] = feature_metrics
            metrics[stage.name] = stage_metrics
        return metrics

    def _collect_feature_metric_files(self, stage: StageInfo) -> dict[str, Any]:
        feature_metrics = {}
        for path in sorted((stage.directory / "feature").glob("*.json")):
            payload = self._read_json(path)
            if not payload:
                continue
            feature_metrics[path.name] = payload
            self._record_raw_ref(stage, path, "feature_summary_json", {})
        return feature_metrics

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _build_summary(
        self,
        flow: dict,
        parameters: dict,
        stages: list[StageInfo],
        metrics: dict,
        entity_counts: dict,
        labels: dict,
        def_data: dict[str, DefData],
        sta_reports: dict[str, dict[str, Any]],
        drc_reports: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        ppa_metrics = self._build_ppa_metrics(metrics, stages, labels, def_data, sta_reports, drc_reports)
        return {
            "workspace": str(self.workspace_dir),
            "flow": _summary_flow(flow, stages),
            "parameters": parameters,
            "stage_count": len(stages),
            "metrics": ppa_metrics,
            "entity_counts": entity_counts,
            "labels": labels,
        }

    def _build_summary_parameters(self, parameters: dict[str, Any], stages: list[StageInfo], def_data: dict[str, DefData]) -> dict[str, Any]:
        del def_data
        normalized = self._engineer_settable_parameters(parameters)
        normalized["control_knobs"] = self._collect_control_knobs(stages)
        return normalized

    @staticmethod
    def _engineer_settable_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
        normalized = json.loads(json.dumps(parameters))
        normalized.pop("PDK Root", None)
        normalized.pop("Die", None)
        core = normalized.get("Core")
        if isinstance(core, dict):
            allowed_core = {
                key: core[key]
                for key in ("Utilitization", "Margin", "Aspect ratio")
                if key in core
            }
            if allowed_core:
                normalized["Core"] = allowed_core
            else:
                normalized.pop("Core", None)
        return normalized

    def _collect_control_knobs(self, stages: list[StageInfo]) -> dict[str, Any]:
        knobs: dict[str, Any] = {"source": "effective_tool_flow_configs"}
        floorplan = self._first_config_values(stages, "fp_default_config.json", {"tap_distance": ("Floorplan", "Tap distance")})
        if floorplan:
            knobs["floorplan"] = floorplan
        dreamplace = self._first_config_values(
            [stage for stage in stages if stage.tool == "dreamplace"],
            "dreamplace.json",
            {
                "num_bins_x": ("num_bins_x",),
                "num_bins_y": ("num_bins_y",),
                "global_place_stages": ("global_place_stages",),
                "density_weight": ("density_weight",),
                "random_seed": ("random_seed",),
                "route_num_bins_x": ("route_num_bins_x",),
                "route_num_bins_y": ("route_num_bins_y",),
                "unit_horizontal_capacity": ("unit_horizontal_capacity",),
                "unit_vertical_capacity": ("unit_vertical_capacity",),
                "max_route_opt_adjust_rate": ("max_route_opt_adjust_rate",),
            },
        )
        if dreamplace:
            knobs["dreamplace"] = dreamplace
        fix_fanout = self._first_config_values(
            [stage for stage in stages if stage.name == "fixFanout"],
            "no_default_config_fixfanout.json",
            {"insert_buffer": ("insert_buffer",)},
        )
        if fix_fanout:
            knobs["fix_fanout"] = fix_fanout
        cts = self._first_config_values(
            [stage for stage in stages if stage.name == "CTS"],
            "cts_default_config.json",
            {
                "router_type": ("router_type",),
                "cluster_type": ("cluster_type",),
                "skew_bound": ("skew_bound",),
                "max_buf_tran": ("max_buf_tran",),
                "max_sink_tran": ("max_sink_tran",),
                "max_cap": ("max_cap",),
                "routing_layer": ("routing_layer",),
                "buffer_type": ("buffer_type",),
                "root_buffer_type": ("root_buffer_type",),
            },
        )
        if cts:
            knobs["cts"] = cts
        route = self._first_config_values(
            [stage for stage in stages if stage.name == "route"],
            "rt_default_config.json",
            {
                "thread_number": ("RT", "-thread_number"),
                "enable_timing": ("RT", "-enable_timing"),
            },
        )
        if route:
            knobs["route"] = route
        return knobs


    def _build_ppa_metrics(
        self,
        metrics: dict[str, Any],
        stages: list[StageInfo],
        labels: dict[str, Any],
        def_data: dict[str, DefData],
        sta_reports: dict[str, dict[str, Any]],
        drc_reports: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        del labels
        ppa_metrics: dict[str, Any] = {}
        for stage in stages:
            stage_metrics: dict[str, Any] = {}
            for payload in metrics.get(stage.name, {}).values():
                if isinstance(payload, dict):
                    stage_metrics.update(_extract_ppa_metric_values(payload))
            parsed_def = def_data.get(stage.name)
            if parsed_def:
                scale = _def_unit_scale(parsed_def)
                stage_metrics.update(
                    {
                        "die_area": _bbox_area(_scale_bbox(parsed_def.diearea, scale) if parsed_def.diearea else None),
                        "wire_count": sum(len(net.wires) for net in parsed_def.nets),
                        "wire_length": sum(wire.length for net in parsed_def.nets for wire in net.wires) * scale,
                        "via_count": sum(1 for net in parsed_def.nets for wire in net.wires if wire.via),
                    }
                )
            sta_report = sta_reports.get(stage.name)
            if sta_report:
                slacks = [_to_float(record.get("slack")) for record in sta_report.get("records", []) if isinstance(record, dict)]
                slacks = [value for value in slacks if value is not None]
                if slacks:
                    stage_metrics["worst_slack"] = min(slacks)
            drc_report = drc_reports.get(stage.name)
            if drc_report:
                stage_metrics["drc_violation_count"] = drc_report.get("count", 0)
            route_feature_metrics = _extract_route_ppa_metrics(metrics.get(stage.name, {}).get("features", {}))
            if route_feature_metrics:
                stage_metrics.update(route_feature_metrics)
            ppa_metrics[stage.name] = {key: value for key, value in stage_metrics.items() if value is not None}
        return ppa_metrics

    def _first_config_values(self, stages: list[StageInfo], filename: str, paths: dict[str, tuple[str, ...]]) -> dict[str, Any]:
        for stage in stages:
            config_path = stage.directory / "config" / filename
            payload = self._read_json(config_path)
            if not payload:
                continue
            values = {name: _get_nested(payload, path) for name, path in paths.items()}
            return {name: value for name, value in values.items() if value is not None}
        return {}

    def _build_manifest(self, stages: list[StageInfo], raw_maps: dict, summary: dict, *, options: dict[str, Any]) -> dict[str, Any]:
        del stages, raw_maps, summary
        artifacts = {
            "summary": str((self.foundation_dir / "summary.json").relative_to(self.workspace_dir)),
            "stage_index": str((self.foundation_dir / "stage_index.json").relative_to(self.workspace_dir)),
            "canonical_grid": str((self.foundation_dir / "canonical_grid.json").relative_to(self.workspace_dir)),
            "quality": str((self.foundation_dir / "quality.json").relative_to(self.workspace_dir)),
            "ml_view": str((self.foundation_dir / "views" / "ml" / "dataset_index.json").relative_to(self.workspace_dir)),
            "agent_view": str((self.foundation_dir / "views" / "agent" / "run_summary.json").relative_to(self.workspace_dir)),
        }
        if options.get("include_raw_refs"):
            artifacts["raw_refs"] = str((self.foundation_dir / "raw_refs" / "artifacts.json").relative_to(self.workspace_dir))
        return {
            "options": options,
            "workspace": str(self.workspace_dir),
            "sources": self._source_signature(),
            "artifacts": artifacts,
        }

    def _source_signature(self) -> list[str]:
        paths = [self.workspace_dir / "home" / "flow.json", self.workspace_dir / "home" / "parameters.json"]
        for stage_dir in self.workspace_dir.glob("*_*"):
            if not stage_dir.is_dir():
                continue
            for folder in ("output", "feature", "analysis", "report", "data"):
                root = stage_dir / folder
                if root.exists():
                    paths.extend(path for path in root.rglob("*") if path.is_file())
        return [str(path.relative_to(self.workspace_dir)) for path in sorted(set(paths)) if path.exists()]

    def _write_views(self, summary: dict, metrics: dict, stage_index: dict, labels: dict, *, include_raw_refs: bool) -> None:
        write_json(
            self.foundation_dir / "views" / "ml" / "dataset_index.json",
            {
                "profile": self.profile,
                "canonical_grid": "canonical_grid.json",
                "vectors_dir": "vectors",
                "maps_dir": "maps/canonical",
                "labels_dir": "labels",
                "tasks": ["route_demand_capacity"],
            },
        )
        write_json(self.foundation_dir / "views" / "ml" / "patch_memory_index.json", {"canonical_grid": "canonical_grid.json", "progressive_inputs": {"P1": ["Floorplan"], "P2": ["Floorplan", "place"], "P3": ["Floorplan", "place", "CTS"]}})
        write_json(
            self.foundation_dir / "views" / "agent" / "run_summary.json",
            {
                "profile": self.profile,
                "workspace": summary["workspace"],
                "stages": _summary_stages(summary),
                "entity_counts": summary["entity_counts"],
                "quality_warnings": self._quality.get("warnings", []),
                "evidence_index": "views/agent/evidence_index.json",
            },
        )
        write_json(self.foundation_dir / "views" / "agent" / "qor_snapshot.json", {"metrics": metrics, "labels": labels})
        write_json(
            self.foundation_dir / "views" / "agent" / "evidence_index.json",
            {
                "stage_index": stage_index,
                "raw_refs": "raw_refs/artifacts.json" if include_raw_refs else None,
                "raw_refs_disabled": not include_raw_refs,
            },
        )

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


def _drc_for_patch(drc_report: dict[str, Any] | None, bbox: dict[str, Any]) -> dict[str, Any]:
    if not drc_report or not drc_report.get("available"):
        return {"count": None, "by_type": {}, "by_layer": {}, "unlocalized_count": None, "availability": "missing"}
    violations = drc_report.get("violations", [])
    if not violations:
        total = int(drc_report.get("count") or 0)
        return {"count": 0 if total == 0 else None, "by_type": {}, "by_layer": {}, "unlocalized_count": total or 0}
    count = 0
    by_type: dict[str, int] = {}
    by_layer: dict[str, int] = {}
    unlocalized = 0
    for violation in violations:
        amount = int(violation.get("count") or 1)
        violation_bbox = violation.get("bbox")
        if not violation_bbox:
            unlocalized += amount
            continue
        if not _bbox_intersects_bbox(violation_bbox, bbox):
            continue
        count += amount
        violation_type = str(violation.get("type") or "unknown")
        by_type[violation_type] = by_type.get(violation_type, 0) + amount
        layer = violation.get("layer")
        if layer:
            layer_name = str(layer)
            by_layer[layer_name] = by_layer.get(layer_name, 0) + amount
    return {"count": count, "by_type": by_type, "by_layer": by_layer, "unlocalized_count": unlocalized}


def _timing_for_patch(timing_paths: list[dict[str, Any]]) -> dict[str, Any]:
    slacks = [float(item["slack"]) for item in timing_paths if item.get("slack") is not None]
    return {
        "worst_slack": min(slacks) if slacks else None,
        "path_count": len(timing_paths) if timing_paths else 0,
        "availability": "available" if timing_paths else "missing",
        "scope": "stage",
    }


def _electrical_for_patch(timing_paths: list[dict[str, Any]]) -> dict[str, Any]:
    caps: list[float] = []
    slews: list[float] = []
    resistances: list[float] = []
    incrs: list[float] = []
    for path in timing_paths:
        electrical = path.get("wire_electrical", {})
        if not isinstance(electrical, dict):
            continue
        caps.extend(float(value) for value in electrical.get("capacitance_list", []) if value is not None)
        slews.extend(float(value) for value in electrical.get("slew_list", []) if value is not None)
        resistances.extend(float(value) for value in electrical.get("resistance_list", []) if value is not None)
        incrs.extend(float(value) for value in electrical.get("incr_delay_list", []) if value is not None)
    return {
        "capacitance_sum": sum(caps) if caps else None,
        "max_slew": max(slews) if slews else None,
        "resistance_sum": sum(resistances) if resistances else None,
        "incr_delay_sum": sum(incrs) if incrs else None,
        "availability": "available" if caps or slews or resistances or incrs else "missing",
        "scope": "stage",
    }


def _bbox_intersects_bbox(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return not (
        float(a["urx"]) < float(b["llx"])
        or float(a["llx"]) > float(b["urx"])
        or float(a["ury"]) < float(b["lly"])
        or float(a["lly"]) > float(b["ury"])
    )


def _demand_capacity_label(label: dict[str, Any]) -> dict[str, Any]:
    h_demand = label.get("horizontal_demand")
    v_demand = label.get("vertical_demand")
    h_capacity = label.get("horizontal_capacity")
    v_capacity = label.get("vertical_capacity")
    return {
        "horizontal": label.get("horizontal_demand_capacity"),
        "vertical": label.get("vertical_demand_capacity"),
        "union": label.get("union_demand_capacity"),
        "horizontal_demand": h_demand,
        "vertical_demand": v_demand,
        "horizontal_capacity": h_capacity,
        "vertical_capacity": v_capacity,
        "horizontal_utilization": label.get("horizontal_utilization"),
        "vertical_utilization": label.get("vertical_utilization"),
        "source": label.get("source"),
    }



def _extract_ppa_metric_values(payload: dict[str, Any]) -> dict[str, Any]:
    ppa_tokens = ("wns", "tns", "frequency", "area", "wire_length", "wirelength", "via", "drc", "buffer", "util", "power", "slack")
    blocked_tokens = ("path", "source", "map", "distribution", "creator", "invocation")
    out: dict[str, Any] = {}
    for key, value in payload.items():
        lower = str(key).lower()
        if any(token in lower for token in blocked_tokens):
            continue
        if any(token in lower for token in ppa_tokens) and isinstance(value, str | int | float | bool | type(None)):
            out[str(key)] = value
    return out


def _extract_route_ppa_metrics(features: Any) -> dict[str, Any]:
    if not isinstance(features, dict):
        return {}
    route_step = features.get("route.step.json")
    if not isinstance(route_step, dict):
        return {}
    route_payload = route_step.get("route")
    if not isinstance(route_payload, dict):
        return {}
    dr_iters = route_payload.get("DR")
    if not isinstance(dr_iters, list) or not dr_iters or not isinstance(dr_iters[-1], dict):
        return {}
    last_iter = dr_iters[-1]
    return {
        "route_wire_length": last_iter.get("total_wire_length"),
        "route_via_count": last_iter.get("total_via_num"),
        "route_violation_count": last_iter.get("total_violation_num"),
    }

def _demand_capacity_source(label: dict[str, Any], reconstructed: dict[str, Any]) -> dict[str, Any]:
    if any(label.get(key) is not None for key in ("horizontal_demand_capacity", "vertical_demand_capacity", "union_demand_capacity")):
        return label
    return reconstructed


def _strip_empty_info(flow: dict[str, Any]) -> dict[str, Any]:
    normalized = json.loads(json.dumps(flow))
    steps = normalized.get("steps")
    if isinstance(steps, list):
        for step in steps:
            if isinstance(step, dict) and step.get("info") == {}:
                step.pop("info", None)
    return normalized


def _summary_flow(flow: dict[str, Any], stages: list[StageInfo]) -> dict[str, Any]:
    normalized = _strip_empty_info(flow)
    steps = normalized.get("steps")
    if isinstance(steps, list):
        by_name = {step.get("name"): step for step in steps if isinstance(step, dict)}
        normalized["steps"] = [by_name[stage.name] for stage in stages if stage.name in by_name]
    return normalized


def _summary_stages(summary: dict[str, Any]) -> list[dict[str, Any]]:
    steps = summary.get("flow", {}).get("steps", [])
    if not isinstance(steps, list):
        return []
    stages = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        stages.append({key: step.get(key) for key in ("name", "tool", "state") if key in step})
    return stages


def _scale_bbox(bbox: dict[str, float] | None, scale: float) -> dict[str, float] | None:
    if bbox is None:
        return None
    return {key: float(value) * scale for key, value in bbox.items()}


def _layout_unit_scale(payload: dict[str, Any]) -> float:
    raw_units = str(payload.get("units", "")).split()
    if raw_units:
        unit = _to_float(raw_units[0])
        if unit is not None and unit > 0:
            return unit
    return 1.0


def _def_unit_scale(parsed_def: DefData) -> float:
    return 1.0 / float(parsed_def.units) if parsed_def.units else 1.0


def _bbox_area(bbox: dict[str, Any] | None) -> float | None:
    if not bbox:
        return None
    return max(0.0, float(bbox["urx"]) - float(bbox["llx"])) * max(0.0, float(bbox["ury"]) - float(bbox["lly"]))


def _get_nested(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    value: Any = payload
    for key in path:
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def _safe_ratio(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator


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
