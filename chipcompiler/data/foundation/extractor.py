from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .grid.canonical_grid import build_patch_grid, resize_nearest
from .parsers.map_csv import read_numeric_csv, shape
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
        self._quality: dict[str, Any] = {"profile": profile, "availability": {}, "warnings": []}
        self._raw_refs: list[dict[str, Any]] = []

    def extract(self, *, force: bool = False) -> ExtractionResult:
        del force  # The current post-run extractor is deterministic and always rewrites outputs.
        if self.foundation_dir.exists():
            shutil.rmtree(self.foundation_dir)
        flow = self._read_json(self.workspace_dir / "home" / "flow.json")
        parameters = self._read_json(self.workspace_dir / "home" / "parameters.json")
        stages = self._stage_infos(flow)
        raw_maps = self._collect_raw_maps(stages)
        die_bbox = self._discover_die_bbox(stages)
        canonical_grid = self._build_canonical_grid(raw_maps, die_bbox)
        canonical_maps = self._write_maps(raw_maps, canonical_grid)
        entity_counts = self._write_vectors(stages, canonical_grid, canonical_maps)
        labels = self._write_labels(canonical_grid, canonical_maps, raw_maps)
        stage_index = self._build_stage_index(stages)
        metrics = self._collect_metrics(stages)
        summary = self._build_summary(flow, parameters, stages, metrics, entity_counts, labels)
        manifest = self._build_manifest(stages, raw_maps, summary)

        write_json(self.foundation_dir / "canonical_grid.json", canonical_grid)
        write_json(self.foundation_dir / "stage_index.json", stage_index)
        write_json(self.foundation_dir / "summary.json", summary)
        write_json(self.foundation_dir / "raw_refs" / "artifacts.json", {"artifacts": self._raw_refs})
        write_json(self.foundation_dir / "quality.json", self._quality)
        write_json(self.foundation_dir / "manifest.json", manifest)
        self._write_views(summary, metrics, stage_index, labels)

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

    def _write_vectors(self, stages: list[StageInfo], canonical_grid: dict, canonical_maps: dict) -> dict[str, dict[str, int]]:
        counts: dict[str, dict[str, int]] = {entity: {} for entity in _ENTITY_NAMES}
        for stage in stages:
            instances = self._parse_instances(stage)
            counts["instances"][stage.name] = write_jsonl(self.foundation_dir / "vectors" / "instances" / f"{stage.name}-00000.jsonl", instances)
            for entity in ("nets", "pins", "wires", "routing_graphs", "timing_paths"):
                counts[entity][stage.name] = write_jsonl(self.foundation_dir / "vectors" / entity / f"{stage.name}-00000.jsonl", [])
                self._quality.setdefault("availability", {}).setdefault(entity, {})[stage.name] = "missing"
            patches = self._patch_records(stage.name, canonical_grid, canonical_maps.get(stage.name, {}))
            counts["patches"][stage.name] = write_jsonl(self.foundation_dir / "vectors" / "patches" / f"{stage.name}-00000.jsonl", patches)
            self._quality.setdefault("availability", {}).setdefault("patches", {})[stage.name] = "available" if patches else "missing"
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
                    }
                )
            if records:
                break
        self._quality.setdefault("availability", {}).setdefault("instances", {})[stage.name] = "available" if records else "missing"
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
    def _patch_records(stage: str, canonical_grid: dict, stage_maps: dict[str, dict[str, list[list[float]]]]) -> list[dict[str, Any]]:
        records = []
        density_maps = stage_maps.get("density", {})
        egr_maps = stage_maps.get("egr_overflow", {})
        for patch in canonical_grid.get("patches", []):
            row = int(patch["row"])
            col = int(patch["col"])
            record = {
                "patch_id": patch["patch_id"],
                "stage": stage,
                "row": row,
                "col": col,
                "bbox": patch["bbox"],
                "cell_density": _value_from_named_map(density_maps, "allcell_density", row, col),
                "pin_density": _value_from_named_map(density_maps, "pin_density", row, col),
                "net_density": _value_from_named_map(density_maps, "net_density", row, col),
                "macro_density": _value_from_named_map(density_maps, "macro_density", row, col),
                "rudy_congestion": None,
                "egr_overflow_horizontal": _matrix_value(egr_maps.get("horizontal"), row, col),
                "egr_overflow_vertical": _matrix_value(egr_maps.get("vertical"), row, col),
                "egr_overflow_union": _matrix_value(egr_maps.get("union"), row, col),
                "source": "canonical_grid",
                "availability": "available",
            }
            records.append(record)
        return records

    def _write_labels(self, canonical_grid: dict, canonical_maps: dict, raw_maps: dict) -> dict[str, Any]:
        route_maps = canonical_maps.get("route", {}).get("egr_overflow", {})
        rows = int(canonical_grid["rows"])
        cols = int(canonical_grid["cols"])
        if not any(route_maps.values()):
            write_jsonl(self.foundation_dir / "labels" / "route_patch_overflow.jsonl", [])
            for percent in (5, 10, 20):
                write_jsonl(self.foundation_dir / "labels" / f"route_hotspot_top{percent}.jsonl", [])
            candidate_summary = {
                "available": False,
                "score_kind": "topavg_H_plus_topavg_V",
                "top_average": {"horizontal": None, "vertical": None, "union": None},
                "patch_count": rows * cols,
                "score": None,
            }
            write_json(self.foundation_dir / "labels" / "candidate_qor_summary.json", candidate_summary)
            self._quality.setdefault("availability", {}).setdefault("labels", {})["route_patch_overflow"] = "missing"
            self._quality.setdefault("warnings", []).append("route EGR overflow maps missing; route labels were not generated")
            return {"route_patch_overflow_count": 0, "candidate_qor_summary": candidate_summary}

        labels = []
        for patch in canonical_grid.get("patches", []):
            row = int(patch["row"])
            col = int(patch["col"])
            h = _matrix_value(route_maps.get("horizontal"), row, col)
            v = _matrix_value(route_maps.get("vertical"), row, col)
            union = _matrix_value(route_maps.get("union"), row, col)
            labels.append(
                {
                    "patch_id": patch["patch_id"],
                    "row": row,
                    "col": col,
                    "horizontal_overflow": h,
                    "vertical_overflow": v,
                    "union_overflow": union if union is not None else max(h or 0.0, v or 0.0),
                    "source": "route_egr_overflow",
                }
            )
        write_jsonl(self.foundation_dir / "labels" / "route_patch_overflow.jsonl", labels)
        for percent in (5, 10, 20):
            write_jsonl(self.foundation_dir / "labels" / f"route_hotspot_top{percent}.jsonl", _hotspot_records(labels, percent))
        candidate_summary = {
            "available": True,
            "score_kind": "topavg_H_plus_topavg_V",
            "top_average": self._top_average_from_raw(raw_maps.get("route", {}).get("egr_overflow", {})),
            "patch_count": rows * cols,
        }
        topavg = candidate_summary["top_average"]
        candidate_summary["score"] = float(topavg.get("horizontal") or 0.0) + float(topavg.get("vertical") or 0.0)
        write_json(self.foundation_dir / "labels" / "candidate_qor_summary.json", candidate_summary)
        self._quality.setdefault("availability", {}).setdefault("labels", {})["route_patch_overflow"] = "available"
        return {"route_patch_overflow_count": len(labels), "candidate_qor_summary": candidate_summary}

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
        write_json(self.foundation_dir / "views" / "agent" / "run_summary.json", {"profile": self.profile, "workspace": summary["workspace"], "stages": summary["stages"], "entity_counts": summary["entity_counts"]})
        write_json(self.foundation_dir / "views" / "agent" / "qor_snapshot.json", {"metrics": metrics, "labels": labels})
        write_json(self.foundation_dir / "views" / "agent" / "evidence_index.json", {"stage_index": stage_index, "raw_refs": "raw_refs/artifacts.json"})

    def _record_raw_ref(self, stage: StageInfo, path: Path, artifact_type: str, metadata: dict[str, Any]) -> None:
        try:
            relative = str(path.relative_to(self.workspace_dir))
        except ValueError:
            relative = str(path)
        self._raw_refs.append({"stage": stage.name, "type": artifact_type, "path": relative, "metadata": metadata})


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
