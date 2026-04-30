from __future__ import annotations

import csv
import json
from pathlib import Path

from chipcompiler.data.foundation import FoundationExtractor


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_csv(path: Path, rows: list[list[object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerows(rows)


def _make_workspace(tmp_path: Path, *, include_route_maps: bool = True) -> Path:
    ws = tmp_path / "sample-ws"
    _write_json(
        ws / "home" / "flow.json",
        {
            "steps": [
                {"name": "Floorplan", "tool": "ecc", "state": "Success"},
                {"name": "place", "tool": "dreamplace", "state": "Success"},
                {"name": "route", "tool": "ecc", "state": "Success"},
            ]
        },
    )
    _write_json(ws / "home" / "parameters.json", {"Core": {"Utilitization": 0.5}})
    for stage_dir, stage_name in [
        ("Floorplan_ecc", "Floorplan"),
        ("place_dreamplace", "place"),
        ("route_ecc", "route"),
    ]:
        _write_json(ws / stage_dir / "analysis" / f"{stage_name}_metrics.json", {"Tool": "ecc", "max_WNS": "1.0"})
        _write_json(ws / stage_dir / "checklist.json", {"state": "Success"})
        _write_json(
            ws / stage_dir / "output" / f"gcd_{stage_name}.json",
            {
                "design name": "gcd",
                "diearea": {"path": [[0, 0], [200, 0], [200, 200], [0, 200], [0, 0]]},
                "layerInfo": [{"id": 0, "layername": "cell"}, {"id": 2, "layername": "M1"}],
                "data": [
                    {
                        "type": "group",
                        "struct name": "Instance_U1",
                        "children": [
                            {"type": "box", "layer": 0, "path": [[0, 0], [10, 0], [10, 20], [0, 20], [0, 0]]}
                        ],
                    },
                    {
                        "type": "group",
                        "struct name": "Macro_SRAM0",
                        "children": [
                            {"type": "box", "layer": 0, "path": [[50, 50], [100, 50], [100, 100], [50, 100], [50, 50]]}
                        ],
                    },
                ],
            },
        )

    _write_csv(ws / "place_dreamplace" / "feature" / "density_map" / "place_allcell_density.csv", [[1, 2], [3, 4]])
    _write_csv(ws / "place_dreamplace" / "feature" / "egr_congestion_map" / "place_egr_horizontal_overflow.csv", [[5]])
    _write_csv(ws / "place_dreamplace" / "feature" / "egr_congestion_map" / "place_egr_vertical_overflow.csv", [[7]])
    _write_json(
        ws / "place_dreamplace" / "feature" / "place.map.json",
        {
            "Density": {"cell": {"allcell_density": "density_map/place_allcell_density.csv"}},
            "Congestion": {
                "map": {"egr": {"horizontal": "egr_congestion_map/place_egr_horizontal_overflow.csv", "vertical": "egr_congestion_map/place_egr_vertical_overflow.csv"}},
                "overflow": {"top_average": {"horizontal": 5, "vertical": 7}},
            },
        },
    )
    if include_route_maps:
        _write_csv(ws / "route_ecc" / "feature" / "egr_congestion_map" / "route_egr_horizontal_overflow.csv", [[1, 0], [2, 3]])
        _write_csv(ws / "route_ecc" / "feature" / "egr_congestion_map" / "route_egr_vertical_overflow.csv", [[0, 4], [1, 1]])
        _write_csv(ws / "route_ecc" / "feature" / "egr_congestion_map" / "route_egr_union_overflow.csv", [[1, 4], [3, 4]])
        _write_json(
            ws / "route_ecc" / "feature" / "route.map.json",
            {
                "Congestion": {
                    "map": {
                        "egr": {
                            "horizontal": "egr_congestion_map/route_egr_horizontal_overflow.csv",
                            "vertical": "egr_congestion_map/route_egr_vertical_overflow.csv",
                            "union": "egr_congestion_map/route_egr_union_overflow.csv",
                        }
                    },
                    "overflow": {"top_average": {"horizontal": 2.5, "vertical": 3.0}},
                }
            },
        )
    return ws


def test_iccd_full_v1_extractor_writes_full_contract(tmp_path: Path):
    ws = _make_workspace(tmp_path)

    result = FoundationExtractor(ws, profile="iccd_full_v1").extract()

    foundation_dir = ws / "foundation_data" / "ecc"
    assert result.foundation_dir == foundation_dir
    for rel in [
        "manifest.json",
        "summary.json",
        "stage_index.json",
        "quality.json",
        "canonical_grid.json",
        "views/ml/dataset_index.json",
        "views/agent/run_summary.json",
        "labels/route_patch_overflow.jsonl",
        "vectors/instances/place-00000.jsonl",
        "vectors/patches/place-00000.jsonl",
        "maps/canonical/place/density.json",
        "maps/canonical/route/egr_overflow.json",
    ]:
        assert (foundation_dir / rel).exists(), rel

    grid = json.loads((foundation_dir / "canonical_grid.json").read_text(encoding="utf-8"))
    assert grid["rows"] == 2
    assert grid["cols"] == 2
    assert len(grid["patches"]) == 4

    canonical_place = json.loads((foundation_dir / "maps" / "canonical" / "place" / "egr_overflow.json").read_text())
    assert canonical_place["horizontal"] == [[5.0, 5.0], [5.0, 5.0]]
    assert canonical_place["vertical"] == [[7.0, 7.0], [7.0, 7.0]]

    instances = [json.loads(line) for line in (foundation_dir / "vectors" / "instances" / "place-00000.jsonl").read_text().splitlines()]
    assert {item["name"] for item in instances} == {"Instance_U1", "Macro_SRAM0"}
    assert any(item["is_macro"] for item in instances)

    labels = [json.loads(line) for line in (foundation_dir / "labels" / "route_patch_overflow.jsonl").read_text().splitlines()]
    assert labels[0]["horizontal_overflow"] == 1.0
    assert labels[1]["vertical_overflow"] == 4.0

    quality = json.loads((foundation_dir / "quality.json").read_text(encoding="utf-8"))
    assert quality["profile"] == "iccd_full_v1"
    assert quality["availability"]["instances"]["place"] == "available"


def test_iccd_full_v1_marks_labels_missing_without_route_maps(tmp_path: Path):
    ws = _make_workspace(tmp_path, include_route_maps=False)

    FoundationExtractor(ws, profile="iccd_full_v1").extract()

    foundation_dir = ws / "foundation_data" / "ecc"
    labels = (foundation_dir / "labels" / "route_patch_overflow.jsonl").read_text(encoding="utf-8")
    candidate = json.loads((foundation_dir / "labels" / "candidate_qor_summary.json").read_text(encoding="utf-8"))
    quality = json.loads((foundation_dir / "quality.json").read_text(encoding="utf-8"))
    summary = json.loads((foundation_dir / "summary.json").read_text(encoding="utf-8"))

    assert labels == ""
    assert candidate["available"] is False
    assert candidate["score"] is None
    assert quality["availability"]["labels"]["route_patch_overflow"] == "missing"
    assert summary["labels"]["route_patch_overflow_count"] == 0


def test_iccd_full_v1_cleans_stale_outputs_before_rewrite(tmp_path: Path):
    ws = _make_workspace(tmp_path)
    foundation_dir = ws / "foundation_data" / "ecc"
    stale = foundation_dir / "vectors" / "instances" / "old-00000.jsonl"
    stale.parent.mkdir(parents=True)
    stale.write_text('{"stale": true}\n', encoding="utf-8")

    FoundationExtractor(ws, profile="iccd_full_v1").extract()

    assert not stale.exists()
