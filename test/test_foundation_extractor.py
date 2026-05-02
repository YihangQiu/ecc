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


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_sample_gcell_info(stage_dir: Path) -> None:
    _write_text(
        stage_dir / "data" / "rt" / "rt_temp_directory" / "early_router" / "gcell.info",
        "\n".join(
            [
                "0,0,0,0,120,80",
                "0,1,0,80,120,200",
                "1,0,120,0,200,80",
                "1,1,120,80,200,200",
            ]
        )
        + "\n",
    )


def _make_workspace(tmp_path: Path, *, include_route_artifacts: bool = True, include_route_maps: bool = True, include_native_route_overflow: bool = True) -> Path:
    ws = tmp_path / "sample-ws"
    _write_json(
        ws / "home" / "flow.json",
        {
            "steps": [
                {"name": "Floorplan", "tool": "ecc", "state": "Success"},
                {"name": "place", "tool": "dreamplace", "state": "Success"},
                {"name": "route", "tool": "ecc", "state": "Success"},
                {"name": "drc", "tool": "ecc", "state": "Success"},
            ]
        },
    )
    _write_json(ws / "home" / "parameters.json", {"Core": {"Utilitization": 0.5}})
    for stage_dir, stage_name in [
        ("Floorplan_ecc", "Floorplan"),
        ("place_dreamplace", "place"),
        ("route_ecc", "route"),
        ("drc_ecc", "drc"),
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
    _write_csv(ws / "place_dreamplace" / "feature" / "density_map" / "place_macro_density.csv", [[1, 2], [3, 4]])
    _write_csv(ws / "place_dreamplace" / "feature" / "density_map" / "place_stdcell_density.csv", [[1, 2], [3, 4]])
    _write_csv(ws / "place_dreamplace" / "feature" / "margin_map" / "place_horizontal_margin.csv", [[1, 2], [3, 4]])
    _write_csv(ws / "place_dreamplace" / "feature" / "margin_map" / "place_vertical_margin.csv", [[1, 2], [3, 4]])
    _write_csv(ws / "place_dreamplace" / "feature" / "margin_map" / "place_union_margin.csv", [[1, 2], [3, 4]])
    _write_csv(ws / "place_dreamplace" / "feature" / "RUDY_map" / "place_rudy_union.csv", [[1, 2], [3, 4]])
    _write_csv(ws / "place_dreamplace" / "feature" / "gcell_patch_map" / "density_map" / "place_allcell_density.csv", [[10, 11], [12, 13]])
    _write_csv(ws / "place_dreamplace" / "feature" / "gcell_patch_map" / "density_map" / "place_allcell_pin_density.csv", [[20, 21], [22, 23]])
    _write_csv(ws / "place_dreamplace" / "feature" / "gcell_patch_map" / "density_map" / "place_allnet_density.csv", [[30, 31], [32, 33]])
    _write_csv(ws / "place_dreamplace" / "feature" / "gcell_patch_map" / "margin_map" / "place_union_margin.csv", [[40, 41], [42, 43]])
    _write_csv(ws / "place_dreamplace" / "feature" / "gcell_patch_map" / "RUDY_map" / "place_rudy_union.csv", [[50, 51], [52, 53]])
    _write_csv(ws / "place_dreamplace" / "feature" / "egr_congestion_map" / "place_egr_horizontal_overflow.csv", [[5]])
    _write_csv(ws / "place_dreamplace" / "feature" / "egr_congestion_map" / "place_egr_vertical_overflow.csv", [[7]])
    _write_text(
        ws / "place_dreamplace" / "output" / "gcd_place.def",
        """
VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN gcd ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 200 200 ) ;
COMPONENTS 1 ;
- U1 NAND2 + PLACED ( 10 20 ) N ;
END COMPONENTS
PINS 1 ;
- OUT + NET n1 + DIRECTION OUTPUT + PLACED ( 180 50 ) N ;
END PINS
NETS 1 ;
- n1 ( U1 A ) ( PIN OUT ) ;
END NETS
END DESIGN
""".strip()
        + "\n",
    )
    _write_sample_gcell_info(ws / "place_dreamplace")
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
    if include_route_artifacts:
        _write_sample_gcell_info(ws / "route_ecc")
        _write_text(
            ws / "route_ecc" / "output" / "gcd_route.def",
            """
VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN gcd ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 200 200 ) ;
TRACKS Y 50 DO 1 STEP 100 LAYER MET2 ;
TRACKS X 50 DO 1 STEP 100 LAYER MET3 ;
GCELLGRID X 0 DO 3 STEP 100 ;
GCELLGRID Y 0 DO 3 STEP 100 ;
VIAS 1 ;
- VIA23 + LAYERS MET2 VIA2 MET3 ;
END VIAS
COMPONENTS 1 ;
- U1 NAND2 + PLACED ( 10 20 ) N ;
END COMPONENTS
PINS 1 ;
- OUT + NET n1 + DIRECTION OUTPUT + PLACED ( 180 50 ) N ;
END PINS
NETS 2 ;
- n1 ( U1 A ) ( PIN OUT )
  + ROUTED MET2 ( 0 50 ) ( 200 * )
    NEW MET2 ( 0 60 ) ( 200 * )
    NEW MET3 ( 50 0 ) ( * 200 )
    NEW MET3 ( 60 0 ) ( * 200 )
    NEW MET3 ( 60 60 ) VIA23
  ;
- n2 ( U1 B ) ( U1 Y ) ;
END NETS
END DESIGN
""".strip()
            + "\n",
        )
        _write_text(
            ws / "route_ecc" / "data" / "rt" / "rt.log",
            """
[RT Info printDatabase]     idx:0 order:9 name:MET2 prefer_direction:horizontal
[RT Info printDatabase]     idx:1 order:11 name:MET3 prefer_direction:vertical
[RT Info printTableList] |      total_demand |       8 |
[RT Info printTableList] |    total_overflow |       4 |
[RT Info printTableList] | total_wire_length |   800.0 |
[RT Info printTableList] | routing | demand | prop | | routing | overflow | prop | | routing | wire_length | prop | | cut | #via | prop |
[RT Info printTableList] | MET2 | 4 | 50.00% | | MET2 | 2 | 50.00% | | MET2 | 400.0 | 50.00% | | VIA2 | 1 | 100.00% |
[RT Info printTableList] | MET3 | 4 | 50.00% | | MET3 | 2 | 50.00% | | MET3 | 400.0 | 50.00% | | Total | 1 | 100.00% |
[RT Info printTableList] | Total | 8 | 100.00% | | Total | 4 | 100.00% | | Total | 800.0 | 100.00% | | Total | 1 | 100.00% |
""".strip()
            + "\n",
        )
        if include_native_route_overflow:
            _write_json(
                ws / "route_ecc" / "data" / "rt" / "patch_overflow.json",
                {
                    "source": "router_native_overflow",
                    "patches": [
                        {
                            "row": 0,
                            "col": 0,
                            "layer": "MET2",
                            "direction": "horizontal",
                            "capacity": 1,
                            "demand": 3,
                            "overflow": 2,
                        },
                        {
                            "row": 0,
                            "col": 0,
                            "layer": "MET3",
                            "direction": "vertical",
                            "capacity": 1,
                            "demand": 4,
                            "overflow": 3,
                        },
                        {
                            "gcell": [1, 1],
                            "layer": "MET2",
                            "direction": "horizontal",
                            "capacity": 1,
                            "demand": 2,
                        },
                    ],
                },
            )
        _write_json(
            ws / "route_ecc" / "data" / "sta" / "gcd.rpt.json",
            {
                "summary": [{"endpoint": "U1/Y", "clock_group": "clk", "delay_type": "max", "path_delay": "1.0", "path_required": "2.0", "slack": "1.0"}],
                "slack": [{"clock": "clk", "delay_type": "max", "TNS": "0.0", "WNS": "1.0"}],
            },
        )
        _write_json(
            ws / "route_ecc" / "data" / "sta" / "wire_paths" / "wire_path_1.json",
            [
                {"node_0": {"Point": "U1/A", "Capacitance": 0.1, "slew": 0.2, "trans_type": "rise"}},
                {"net_arc_0": {"Incr": 0.3, "Resistance": 1.5}},
                {"node_1": {"Point": "U1/Y", "Capacitance": 0.4, "slew": 0.6, "trans_type": "fall"}},
            ],
        )
        _write_json(
            ws / "drc_ecc" / "data" / "drc" / "violation_map.json",
            [
                {
                    "type": "short",
                    "rule": "M2.SHORT",
                    "layer": "MET2",
                    "bbox": {"llx": 20, "lly": 20, "urx": 80, "ury": 80},
                    "count": 2,
                },
                {
                    "type": "spacing",
                    "rule": "M3.SPACE",
                    "layer": "MET3",
                    "bbox": [120, 120, 180, 180],
                },
            ],
        )
        _write_json(ws / "drc_ecc" / "analysis" / "drc_metrics.json", {"Tool": "ecc", "drc_num": 3})
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
        "vectors/tech/layers.json",
        "vectors/tech/cells.json",
        "vectors/tech/vias.json",
        "vectors/nets/route-00000.jsonl",
        "vectors/pins/route-00000.jsonl",
        "vectors/wires/route-00000.jsonl",
        "vectors/routing_graphs/route-00000.jsonl",
        "vectors/timing_paths/route-00000.jsonl",
        "vectors/patches/place-00000.jsonl",
        "maps/canonical/place/density.json",
        "maps/canonical/route/egr_overflow.json",
    ]:
        assert (foundation_dir / rel).exists(), rel

    grid = json.loads((foundation_dir / "canonical_grid.json").read_text(encoding="utf-8"))
    assert grid["rows"] == 2
    assert grid["cols"] == 2
    assert grid["grid_source"] == "irt_gcell_info"
    assert len(grid["patches"]) == 4
    assert grid["patches"][0]["bbox"] == {"llx": 0.0, "lly": 0.0, "urx": 120.0, "ury": 80.0}
    assert grid["patches"][0]["gcell"] == {"x": 0, "y": 0}

    canonical_place = json.loads((foundation_dir / "maps" / "canonical" / "place" / "egr_overflow.json").read_text())
    assert canonical_place["horizontal"] == [[5.0]]
    assert canonical_place["vertical"] == [[7.0]]

    canonical_density = json.loads((foundation_dir / "maps" / "canonical" / "place" / "density.json").read_text())
    assert canonical_density["place_allcell_density"] == [[10.0, 11.0], [12.0, 13.0]]
    assert canonical_density["place_allcell_pin_density"] == [[20.0, 21.0], [22.0, 23.0]]
    assert canonical_density["place_allnet_density"] == [[30.0, 31.0], [32.0, 33.0]]

    canonical_margin = json.loads((foundation_dir / "maps" / "canonical" / "place" / "margin.json").read_text())
    assert canonical_margin["union"] == [[40.0, 41.0], [42.0, 43.0]]

    canonical_rudy = json.loads((foundation_dir / "maps" / "canonical" / "place" / "rudy.json").read_text())
    assert canonical_rudy["rudy_union"] == [[50.0, 51.0], [52.0, 53.0]]

    instances = [json.loads(line) for line in (foundation_dir / "vectors" / "instances" / "place-00000.jsonl").read_text().splitlines()]
    assert {item["name"] for item in instances} == {"Instance_U1", "Macro_SRAM0"}
    assert any(item["is_macro"] for item in instances)

    labels = [json.loads(line) for line in (foundation_dir / "labels" / "route_patch_overflow.jsonl").read_text().splitlines()]
    assert {item["source"] for item in labels} == {"router_native_overflow"}
    assert labels[0]["horizontal_overflow"] == 2.0
    assert labels[0]["vertical_overflow"] == 3.0
    assert labels[3]["horizontal_overflow"] == 1.0

    nets = [json.loads(line) for line in (foundation_dir / "vectors" / "nets" / "route-00000.jsonl").read_text().splitlines()]
    pins = [json.loads(line) for line in (foundation_dir / "vectors" / "pins" / "route-00000.jsonl").read_text().splitlines()]
    wires = [json.loads(line) for line in (foundation_dir / "vectors" / "wires" / "route-00000.jsonl").read_text().splitlines()]
    timing_paths = [json.loads(line) for line in (foundation_dir / "vectors" / "timing_paths" / "route-00000.jsonl").read_text().splitlines()]
    assert nets[0]["name"] == "n1"
    assert any(pin["pin_name"] == "OUT" for pin in pins)
    assert any(wire["layer"] == "MET2" and wire["direction"] == "horizontal" for wire in wires)
    assert timing_paths and timing_paths[0]["slack"] == 1.0
    assert timing_paths[0]["arc_sequence"][0]["name"] == "U1/A"
    assert timing_paths[0]["wire_electrical"]["capacitance_sum"] == 0.5
    assert timing_paths[0]["wire_electrical"]["max_slew"] == 0.6
    assert timing_paths[0]["wire_electrical"]["resistance_sum"] == 1.5

    patches = [json.loads(line) for line in (foundation_dir / "vectors" / "patches" / "route-00000.jsonl").read_text().splitlines()]
    assert patches[0]["net_count"] >= 1
    assert patches[0]["wire_length_by_layer"]["MET2"] > 0
    assert patches[0]["route_true_overflow"]["union"] == 3.0
    assert patches[0]["route_reconstructed_congestion"]["union"] == 1.0
    assert patches[0]["timing"]["worst_slack"] == 1.0
    assert patches[0]["electrical"]["capacitance_sum"] == 0.5
    assert patches[0]["electrical"]["max_slew"] == 0.6

    drc_patches = [json.loads(line) for line in (foundation_dir / "vectors" / "patches" / "drc-00000.jsonl").read_text().splitlines()]
    assert drc_patches[0]["drc"]["count"] == 2
    assert drc_patches[0]["drc"]["by_type"] == {"short": 2}
    assert drc_patches[-1]["drc"]["count"] == 1

    quality = json.loads((foundation_dir / "quality.json").read_text(encoding="utf-8"))
    assert quality["profile"] == "iccd_full_v1"
    assert quality["availability"]["instances"]["place"] == "available"
    assert quality["availability"]["labels"]["route_patch_overflow"] == "available"
    assert quality["availability"]["drc"]["drc"] == "available"
    assert quality["availability"]["timing_paths"]["route"] == "available"
    assert "null_reason" in quality


def test_iccd_full_v1_marks_labels_missing_without_true_route_artifacts(tmp_path: Path):
    ws = _make_workspace(tmp_path, include_route_artifacts=False, include_route_maps=True)

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
    assert quality["null_reason"]["labels"]["route_patch_overflow"] == "missing_router_native_route_overflow_artifact"
    assert summary["labels"]["route_patch_overflow_count"] == 0


def test_iccd_full_v1_separates_reconstructed_congestion_from_true_route_label(tmp_path: Path):
    ws = _make_workspace(tmp_path, include_native_route_overflow=False)

    FoundationExtractor(ws, profile="iccd_full_v1").extract()

    foundation_dir = ws / "foundation_data" / "ecc"
    true_labels = (foundation_dir / "labels" / "route_patch_overflow.jsonl").read_text(encoding="utf-8")
    reconstructed = [
        json.loads(line)
        for line in (foundation_dir / "labels" / "route_reconstructed_congestion.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    quality = json.loads((foundation_dir / "quality.json").read_text(encoding="utf-8"))
    candidate = json.loads((foundation_dir / "labels" / "candidate_qor_summary.json").read_text(encoding="utf-8"))
    patches = [json.loads(line) for line in (foundation_dir / "vectors" / "patches" / "route-00000.jsonl").read_text().splitlines()]

    assert true_labels == ""
    assert reconstructed
    assert {item["source"] for item in reconstructed} == {"routed_def_tracks_reconstruction"}
    assert reconstructed[0]["horizontal_overflow"] == 1.0
    assert reconstructed[0]["vertical_overflow"] == 1.0
    assert patches[0]["route_true_overflow"]["union"] is None
    assert patches[0]["route_reconstructed_congestion"]["union"] == 1.0
    assert candidate["available"] is False
    assert quality["availability"]["labels"]["route_patch_overflow"] == "missing"
    assert quality["null_reason"]["labels"]["route_patch_overflow"] == "missing_router_native_route_overflow_artifact"
    assert quality["availability"]["labels"]["route_reconstructed_congestion"] == "available"


def test_iccd_full_v1_cleans_stale_outputs_before_rewrite(tmp_path: Path):
    ws = _make_workspace(tmp_path)
    foundation_dir = ws / "foundation_data" / "ecc"
    stale = foundation_dir / "vectors" / "instances" / "old-00000.jsonl"
    stale.parent.mkdir(parents=True)
    stale.write_text('{"stale": true}\n', encoding="utf-8")

    FoundationExtractor(ws, profile="iccd_full_v1").extract()

    assert not stale.exists()



def test_iccd_full_v1_honors_stage_filter_and_raw_refs_option(tmp_path: Path):
    ws = _make_workspace(tmp_path)

    FoundationExtractor(ws, profile="iccd_full_v1").extract(stages=["place"], include_raw_refs=False)

    foundation_dir = ws / "foundation_data" / "ecc"
    summary = json.loads((foundation_dir / "summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((foundation_dir / "manifest.json").read_text(encoding="utf-8"))
    evidence = json.loads((foundation_dir / "views" / "agent" / "evidence_index.json").read_text(encoding="utf-8"))
    quality = json.loads((foundation_dir / "quality.json").read_text(encoding="utf-8"))

    assert [item["name"] for item in summary["stages"]] == ["place"]
    assert (foundation_dir / "vectors" / "instances" / "place-00000.jsonl").exists()
    assert not (foundation_dir / "vectors" / "instances" / "route-00000.jsonl").exists()
    assert not (foundation_dir / "raw_refs" / "artifacts.json").exists()
    assert manifest["options"]["stages"] == ["place"]
    assert manifest["options"]["include_raw_refs"] is False
    assert "raw_refs" not in manifest["artifacts"]
    assert evidence["raw_refs"] is None
    assert evidence["raw_refs_disabled"] is True
    assert quality["availability"]["labels"]["route_patch_overflow"] == "missing"
    assert quality["null_reason"]["labels"]["route_patch_overflow"] == "missing_router_native_route_overflow_artifact"


def test_iccd_full_v1_rejects_unknown_stage_filter(tmp_path: Path):
    ws = _make_workspace(tmp_path)

    try:
        FoundationExtractor(ws, profile="iccd_full_v1").extract(stages=["missing_stage"])
    except ValueError as exc:
        assert "unknown foundation extraction stage" in str(exc)
    else:
        raise AssertionError("expected unknown stage to fail")
