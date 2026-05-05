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


def _write_sample_egr_demand_capacity(stage_dir: Path) -> None:
    early_router = stage_dir / "data" / "rt" / "rt_temp_directory" / "early_router"
    _write_text(
        early_router / "route.guide",
        "\n".join(
            [
                "guide net_name",
                "pin grid_x grid_y real_x real_y layer energy name",
                "wire grid1_x grid1_y grid2_x grid2_y real1_x real1_y real2_x real2_y layer",
                "via grid_x grid_y real_x real_y layer1 layer2",
                "guide n1",
                "wire 0 0 1 0 0 0 120 0 MET2",
                "wire 0 0 0 1 0 0 0 80 MET3",
            ]
        )
        + "\n",
    )
    _write_csv(early_router / "net_map_MET2.csv", [[8, 1], [3, 4]])
    _write_csv(early_router / "supply_map_MET2.csv", [[5, 5], [2, 1]])
    _write_csv(early_router / "net_map_MET3.csv", [[0, 9], [6, 1]])
    _write_csv(early_router / "supply_map_MET3.csv", [[1, 2], [3, 4]])


def _make_workspace(
    tmp_path: Path,
    *,
    include_route_artifacts: bool = True,
    include_route_maps: bool = True,
    include_native_demand_capacity: bool = True,
) -> Path:
    ws = tmp_path / "sample-ws"
    _write_json(
        ws / "home" / "flow.json",
        {
            "steps": [
                {"name": "Floorplan", "tool": "ecc", "state": "Success", "info": {}},
                {"name": "place", "tool": "dreamplace", "state": "Success"},
                {"name": "CTS", "tool": "ecc", "state": "Success"},
                {"name": "route", "tool": "ecc", "state": "Success"},
                {"name": "drc", "tool": "ecc", "state": "Success"},
            ]
        },
    )
    _write_json(
        ws / "home" / "parameters.json",
        {
            "PDK": "ics55",
            "Design": "gcd",
            "Die": {"Size": [], "Area": 0},
            "Core": {"Size": [], "Area": 0, "Utilitization": 0.5, "Margin": [2, 2], "Aspect ratio": 1},
            "Max fanout": 20,
            "Target density": 0.3,
            "Target overflow": 0.1,
            "Cell padding x": 600,
            "Routability opt flag": 1,
            "Bottom layer": "MET2",
            "Top layer": "MET5",
        },
    )
    for stage_dir, stage_name in [
        ("Floorplan_ecc", "Floorplan"),
        ("place_dreamplace", "place"),
        ("CTS_ecc", "CTS"),
        ("route_ecc", "route"),
        ("drc_ecc", "drc"),
    ]:
        _write_json(ws / stage_dir / "analysis" / f"{stage_name}_metrics.json", {"Tool": "ecc", "max_WNS": "1.0"})
        _write_json(ws / stage_dir / "config" / "fp_default_config.json", {"Floorplan": {"Tap distance": 58}})
        _write_json(ws / stage_dir / "config" / "pl_default_config.json", {"PL": {"GP": {"global_right_padding": 0}}})
        _write_json(
            ws / stage_dir / "config" / "rt_default_config.json",
            {"RT": {"-bottom_routing_layer": "MET2", "-top_routing_layer": "MET5", "-thread_number": "50", "-enable_timing": "0"}},
        )
        if "dreamplace" in stage_dir:
            _write_json(
                ws / stage_dir / "config" / "dreamplace.json",
                {
                    "num_bins_x": 32,
                    "num_bins_y": 32,
                    "global_place_stages": [{"iteration": 3000}],
                    "target_density": 0.3,
                    "density_weight": 0.00085,
                    "random_seed": 3000,
                    "route_num_bins_x": 512,
                    "route_num_bins_y": 512,
                    "unit_horizontal_capacity": 1.5625,
                    "unit_vertical_capacity": 1.45,
                    "max_route_opt_adjust_rate": 2.0,
                },
            )
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
    _write_csv(ws / "place_dreamplace" / "feature" / "gcell_patch_map" / "density_map" / "place_global_net_density.csv", [[34, 35], [36, 37]])
    _write_csv(ws / "place_dreamplace" / "feature" / "gcell_patch_map" / "density_map" / "place_local_net_density.csv", [[38, 39], [40, 41]])
    _write_csv(ws / "place_dreamplace" / "feature" / "gcell_patch_map" / "density_map" / "place_macro_density.csv", [[0, 0], [0, 0]])
    _write_csv(ws / "place_dreamplace" / "feature" / "gcell_patch_map" / "density_map" / "place_macro_pin_density.csv", [[0, 0], [0, 0]])
    _write_csv(ws / "place_dreamplace" / "feature" / "gcell_patch_map" / "density_map" / "place_stdcell_density.csv", [[10, 11], [12, 13]])
    _write_csv(ws / "place_dreamplace" / "feature" / "gcell_patch_map" / "density_map" / "place_stdcell_pin_density.csv", [[20, 21], [22, 23]])
    _write_csv(ws / "place_dreamplace" / "feature" / "gcell_patch_map" / "margin_map" / "place_union_margin.csv", [[40, 41], [42, 43]])
    _write_csv(ws / "place_dreamplace" / "feature" / "gcell_patch_map" / "RUDY_map" / "place_rudy_union.csv", [[50, 51], [52, 53]])
    _write_csv(ws / "place_dreamplace" / "feature" / "gcell_patch_map" / "RUDY_map" / "place_lut_rudy_union.csv", [[150, 151], [152, 153]])
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
    _write_text(
        ws / "Floorplan_ecc" / "output" / "gcd_Floorplan.def",
        """
VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN gcd ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 200 200 ) ;
ROW ROW_0 core 0 0 N DO 2 BY 1 STEP 50 10 ;
COMPONENTS 2 ;
- U1 NAND2 + PLACED ( 10 20 ) N ;
- MAC0 SRAM + PLACED ( 50 50 ) N ;
- ENDCAP_0 FILLTAPH7R + FIXED ( 0 0 ) N + SIZE 50 BY 20 ;
END COMPONENTS
PINS 1 ;
- OUT + NET n1 + DIRECTION OUTPUT + PLACED ( 180 50 ) N ;
END PINS
NETS 2 ;
- n1 ( U1 A ) ( PIN OUT ) ;
- n2 ( MAC0 A ) ( U1 Y ) ;
END NETS
SPECIALNETS 1 ;
- VDD ( * VDD )
  + USE POWER
  + ROUTED MET2 10 ( 0 50 ) ( 200 * )
  ;
END SPECIALNETS
END DESIGN
""".strip()
        + "\n",
    )
    _write_sample_gcell_info(ws / "place_dreamplace")
    _write_sample_egr_demand_capacity(ws / "place_dreamplace")
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
        if include_native_demand_capacity:
            _write_text(
                ws / "route_ecc" / "data" / "rt" / "space_router" / "route_native_demand_capacity_final.jsonl",
                "\n".join(
                    [
                        json.dumps(
                            {
                                "row": 0,
                                "col": 0,
                                "gcell": {"x": 0, "y": 0},
                                "layer": "MET2",
                                "layer_idx": 0,
                                "direction": "horizontal",
                                "demand": 6.0,
                                "capacity": 3.0,
                                "demand_capacity": 3.0,
                                "utilization": 2.0,
                                "overflow": 3.0,
                                "source": "irt_space_router_native",
                                "stage": "space_router_final",
                            }
                        ),
                        json.dumps(
                            {
                                "row": 0,
                                "col": 0,
                                "gcell": {"x": 0, "y": 0},
                                "layer": "MET3",
                                "layer_idx": 1,
                                "direction": "vertical",
                                "demand": 4.0,
                                "capacity": 2.0,
                                "demand_capacity": 2.0,
                                "utilization": 2.0,
                                "overflow": 2.0,
                                "source": "irt_space_router_native",
                                "stage": "space_router_final",
                            }
                        ),
                        json.dumps(
                            {
                                "gcell": {"x": 1, "y": 0},
                                "layer": "MET3",
                                "layer_idx": 1,
                                "direction": "vertical",
                                "demand": 8.0,
                                "capacity": 3.0,
                                "demand_capacity": 5.0,
                                "utilization": 2.6666666666666665,
                                "overflow": 5.0,
                                "source": "irt_space_router_native",
                                "stage": "space_router_final",
                            }
                        ),
                        json.dumps(
                            {
                                "row": 1,
                                "col": 1,
                                "gcell": {"x": 1, "y": 1},
                                "layer": "MET2",
                                "layer_idx": 0,
                                "direction": "horizontal",
                                "demand": 1.0,
                                "capacity": 5.0,
                                "demand_capacity": -4.0,
                                "utilization": 0.2,
                                "overflow": 0.0,
                                "source": "irt_space_router_native",
                                "stage": "space_router_final",
                            }
                        ),
                    ]
                )
                + "\n",
            )
        _write_json(
            ws / "route_ecc" / "feature" / "route.step.json",
            {"route": {"DR": [{"iter": 1, "total_wire_length": 800.0, "total_violation_num": 4, "total_via_num": 1}]}},
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


def test_read_numeric_csv_ignores_trailing_empty_columns(tmp_path: Path):
    from chipcompiler.data.foundation.parsers.map_csv import read_numeric_csv, shape

    csv_path = tmp_path / "trailing.csv"
    csv_path.write_text("1,2,\n3,,4,\n", encoding="utf-8")

    matrix = read_numeric_csv(csv_path)

    assert matrix == [[1.0, 2.0], [3.0, 0.0, 4.0]]
    assert shape(matrix) == (2, 3)


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
        "labels/route_native_demand_capacity.jsonl",
        "vectors/instances/place.jsonl",
        "vectors/tech/layers.json",
        "vectors/tech/cells.json",
        "vectors/tech/vias.json",
        "vectors/nets/route.jsonl",
        "vectors/pins/route.jsonl",
        "vectors/wires/route.jsonl",
        "vectors/routing_graphs/route.jsonl",
        "vectors/timing_paths/route.jsonl",
        "vectors/patches/place.jsonl",
        "maps/place/density.json",
        "maps/place/congestion.json",
    ]:
        assert (foundation_dir / rel).exists(), rel
    assert not (foundation_dir / "maps" / "place" / "egr_overflow.json").exists()

    summary = json.loads((foundation_dir / "summary.json").read_text(encoding="utf-8"))
    assert "profile" not in summary
    assert "created_at" not in summary
    assert "stages" not in summary
    assert all("info" not in step for step in summary["flow"]["steps"])
    assert "Die" not in summary["parameters"]
    assert summary["parameters"]["Core"] == {
        "Utilitization": 0.5,
        "Margin": [2, 2],
        "Aspect ratio": 1,
    }
    assert "PDK Root" not in summary["parameters"]
    control_knobs = summary["parameters"]["control_knobs"]
    assert control_knobs["source"] == "effective_tool_flow_configs"
    assert "base" not in control_knobs
    assert "stage_configs" not in control_knobs
    assert "database_inputs" not in control_knobs
    assert "drc" not in control_knobs
    assert "pnp" not in control_knobs
    assert set(control_knobs) == {"source", "floorplan", "dreamplace", "route"}
    assert control_knobs["floorplan"] == {"tap_distance": 58}
    assert control_knobs["dreamplace"]["num_bins_x"] == 32
    assert control_knobs["dreamplace"]["global_place_stages"][0]["iteration"] == 3000
    assert "target_density" not in control_knobs["dreamplace"]
    assert control_knobs["route"] == {"thread_number": "50", "enable_timing": "0"}
    assert "Max fanout" in summary["parameters"]
    assert "Target density" in summary["parameters"]
    assert "Top layer" in summary["parameters"]
    metrics = summary["metrics"]
    assert metrics["route"]["wire_count"] > 0
    assert metrics["route"]["wire_length"] > 0
    assert metrics["route"]["route_via_count"] > 0
    assert "route_patch_overflow_count" not in metrics["route"]
    assert "features" not in metrics["route"]
    assert "route.step.json" not in metrics["route"]
    assert all(all("path" not in key.lower() for key in stage_metrics) for stage_metrics in metrics.values())

    manifest = json.loads((foundation_dir / "manifest.json").read_text(encoding="utf-8"))
    assert set(manifest) == {"options", "workspace", "sources", "artifacts"}
    assert "version" not in manifest
    assert "profile" not in manifest
    assert "created_at" not in manifest
    assert manifest["workspace"] == str(ws.resolve())
    assert isinstance(manifest["sources"], list)
    assert "home/flow.json" in manifest["sources"]
    assert "place_dreamplace/analysis/place_metrics.json" in manifest["sources"]
    assert all(not Path(source).is_absolute() for source in manifest["sources"])
    assert all(isinstance(source, str) for source in manifest["sources"])
    assert manifest["artifacts"] == {
        "summary": "foundation_data/ecc/summary.json",
        "stage_index": "foundation_data/ecc/stage_index.json",
        "canonical_grid": "foundation_data/ecc/canonical_grid.json",
        "quality": "foundation_data/ecc/quality.json",
        "ml_view": "foundation_data/ecc/views/ml/dataset_index.json",
        "agent_view": "foundation_data/ecc/views/agent/run_summary.json",
        "raw_refs": "foundation_data/ecc/raw_refs/artifacts.json",
    }

    grid = json.loads((foundation_dir / "canonical_grid.json").read_text(encoding="utf-8"))
    assert grid["rows"] == 2
    assert grid["cols"] == 2
    assert grid["grid_source"] == "irt_gcell_info"
    assert len(grid["patches"]) == 4
    assert grid["patches"][0]["bbox"] == {"llx": 0.0, "lly": 0.0, "urx": 120.0, "ury": 80.0}
    assert grid["patches"][0]["row"] == 0
    assert grid["patches"][0]["col"] == 0
    assert "gcell" not in grid["patches"][0]

    place_congestion = json.loads((foundation_dir / "maps" / "place" / "congestion.json").read_text())
    assert place_congestion["category"] == "congestion"
    assert [item["value"] for item in place_congestion["maps"]["horizontal"]["values"]] == [1.0, 3.0, 3.0, -4.0]
    assert [item["value"] for item in place_congestion["maps"]["vertical"]["values"]] == [3.0, -3.0, -1.0, 7.0]
    assert [item["value"] for item in place_congestion["maps"]["union"]["values"]] == [3.0, 3.0, 3.0, 7.0]

    indexed_density = json.loads((foundation_dir / "maps" / "place" / "density.json").read_text())
    assert "place_allcell_density" not in indexed_density["maps"]
    assert [item["value"] for item in indexed_density["maps"]["allcell_density"]["values"]] == [10.0, 11.0, 12.0, 13.0]
    assert [item["value"] for item in indexed_density["maps"]["allcell_pin_density"]["values"]] == [20.0, 21.0, 22.0, 23.0]
    assert [item["value"] for item in indexed_density["maps"]["allnet_density"]["values"]] == [30.0, 31.0, 32.0, 33.0]

    indexed_margin = json.loads((foundation_dir / "maps" / "place" / "margin.json").read_text())
    assert [item["value"] for item in indexed_margin["maps"]["union"]["values"]] == [40.0, 41.0, 42.0, 43.0]

    indexed_rudy = json.loads((foundation_dir / "maps" / "place" / "rudy.json").read_text())
    assert [item["value"] for item in indexed_rudy["maps"]["rudy_union"]["values"]] == [50.0, 51.0, 52.0, 53.0]
    assert all("lut" not in key for key in indexed_rudy["maps"])
    assert not (foundation_dir / "maps" / "place" / "ignored.json").exists()
    assert not (foundation_dir / "maps" / "canonical").exists()
    assert not (foundation_dir / "maps" / "raw").exists()

    instances = [json.loads(line) for line in (foundation_dir / "vectors" / "instances" / "place.jsonl").read_text().splitlines()]
    assert {item["name"] for item in instances} == {"Instance_U1", "Macro_SRAM0"}
    assert all("availability" not in item for item in instances)
    assert any(item["is_macro"] for item in instances)

    assert not (foundation_dir / "labels" / "route_patch_overflow.jsonl").exists()
    assert not (foundation_dir / "labels" / "route_hotspot_top5.jsonl").exists()
    assert not (foundation_dir / "labels" / "candidate_qor_summary.json").exists()
    assert not (foundation_dir / "labels" / "route_reconstructed_congestion.jsonl").exists()
    assert not (foundation_dir / "labels" / "route_reconstructed_demand_capacity.jsonl").exists()

    native_demand_capacity = [
        json.loads(line)
        for line in (foundation_dir / "labels" / "route_native_demand_capacity.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert {item["source"] for item in native_demand_capacity} == {"irt_space_router_native"}
    assert native_demand_capacity[0]["horizontal_demand"] == 6.0
    assert native_demand_capacity[0]["horizontal_capacity"] == 3.0
    assert native_demand_capacity[0]["horizontal_demand_capacity"] == 3.0
    assert native_demand_capacity[0]["vertical_demand_capacity"] == 2.0
    assert native_demand_capacity[0]["union_demand_capacity"] == 3.0
    assert native_demand_capacity[1]["vertical_demand_capacity"] == 5.0
    assert native_demand_capacity[2]["union_demand_capacity"] == 0.0

    nets = [json.loads(line) for line in (foundation_dir / "vectors" / "nets" / "route.jsonl").read_text().splitlines()]
    pins = [json.loads(line) for line in (foundation_dir / "vectors" / "pins" / "route.jsonl").read_text().splitlines()]
    wires = [json.loads(line) for line in (foundation_dir / "vectors" / "wires" / "route.jsonl").read_text().splitlines()]
    timing_paths = [json.loads(line) for line in (foundation_dir / "vectors" / "timing_paths" / "route.jsonl").read_text().splitlines()]
    assert nets[0]["name"] == "n1"
    assert all("availability" not in item for item in [*nets, *pins, *wires, *timing_paths])
    assert any(pin["pin_name"] == "OUT" for pin in pins)
    assert any(wire["layer"] == "MET2" and wire["direction"] == "horizontal" for wire in wires)
    assert timing_paths and timing_paths[0]["slack"] == 1.0
    assert timing_paths[0]["arc_sequence"][0]["name"] == "U1/A"
    assert timing_paths[0]["wire_electrical"]["capacitance_sum"] == 0.5
    assert timing_paths[0]["wire_electrical"]["max_slew"] == 0.6
    assert timing_paths[0]["wire_electrical"]["resistance_sum"] == 1.5

    patches = [json.loads(line) for line in (foundation_dir / "vectors" / "patches" / "route.jsonl").read_text().splitlines()]
    assert patches[0]["net_count"] >= 1
    assert "bbox" not in patches[0]
    assert "availability" not in patches[0]
    assert patches[0]["wire_length_by_layer"]["MET2"] > 0
    assert "route_true_overflow" not in patches[0]
    assert "route_reconstructed_congestion" not in patches[0]
    assert patches[0]["route_native_demand_capacity"]["horizontal"] == 3.0
    assert patches[0]["route_native_demand_capacity"]["vertical"] == 2.0
    assert "route_reconstructed_demand_capacity" not in patches[0]
    assert patches[0]["route_demand_capacity"]["horizontal"] == 3.0
    assert patches[0]["route_demand_capacity"]["vertical"] == 2.0
    assert patches[0]["route_demand_capacity"]["source"] == "irt_space_router_native"
    assert patches[0]["timing"]["worst_slack"] == 1.0
    assert patches[0]["electrical"]["capacitance_sum"] == 0.5
    assert patches[0]["electrical"]["max_slew"] == 0.6

    drc_patches = [json.loads(line) for line in (foundation_dir / "vectors" / "patches" / "drc.jsonl").read_text().splitlines()]
    assert drc_patches[0]["drc"]["count"] == 2
    assert drc_patches[0]["drc"]["by_type"] == {"short": 2}
    assert drc_patches[-1]["drc"]["count"] == 1

    quality = json.loads((foundation_dir / "quality.json").read_text(encoding="utf-8"))
    assert "profile" not in quality
    assert quality["availability"]["instances"]["place"] == "available"
    assert quality["availability"]["labels"]["route_native_demand_capacity"] == "available"
    assert "route_reconstructed_demand_capacity" not in quality["availability"]["labels"]
    assert "route_reconstructed_congestion" not in quality["availability"]["labels"]
    assert "route_patch_overflow" not in quality["availability"]["labels"]
    assert quality["availability"]["drc"]["drc"] == "available"
    assert quality["availability"]["timing_paths"]["route"] == "available"
    assert "null_reason" in quality
    assert "route_reconstructed_congestion_count" not in summary["labels"]
    assert "route_reconstructed_demand_capacity_count" not in summary["labels"]



def test_iccd_full_v1_writes_patch_indexed_stage_maps_for_floorplan_place_cts(tmp_path: Path):
    ws = _make_workspace(tmp_path)
    _write_sample_gcell_info(ws / "CTS_ecc")
    _write_sample_egr_demand_capacity(ws / "CTS_ecc")
    _write_csv(ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "density_map" / "cts_allcell_density.csv", [[100, 101], [102, 103]])
    _write_csv(ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "density_map" / "cts_allcell_pin_density.csv", [[104, 105], [106, 107]])
    _write_csv(ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "density_map" / "cts_allnet_density.csv", [[108, 109], [110, 111]])
    _write_csv(ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "density_map" / "cts_global_net_density.csv", [[112, 113], [114, 115]])
    _write_csv(ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "density_map" / "cts_local_net_density.csv", [[116, 117], [118, 119]])
    _write_csv(ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "density_map" / "cts_macro_density.csv", [[0, 0], [0, 0]])
    _write_csv(ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "density_map" / "cts_macro_pin_density.csv", [[124, 125], [126, 127]])
    _write_csv(ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "density_map" / "cts_stdcell_density.csv", [[100, 101], [102, 103]])
    _write_csv(ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "density_map" / "cts_stdcell_pin_density.csv", [[132, 133], [134, 135]])
    _write_csv(ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "RUDY_map" / "cts_rudy_union.csv", [[110, 111], [112, 113]])
    _write_csv(ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "margin_map" / "cts_union_margin.csv", [[120, 121], [122, 123]])
    floorplan_layout = json.loads((ws / "Floorplan_ecc" / "output" / "gcd_Floorplan.json").read_text(encoding="utf-8"))
    floorplan_layout["data"].append(
        {
            "type": "group",
            "struct name": "Instance_ENDCAP_0",
            "children": [
                {"type": "box", "layer": 0, "path": [[0, 0], [50, 0], [50, 20], [0, 20], [0, 0]]}
            ],
        }
    )
    _write_json(ws / "Floorplan_ecc" / "output" / "gcd_Floorplan.json", floorplan_layout)

    FoundationExtractor(ws, profile="iccd_full_v1").extract()

    foundation_dir = ws / "foundation_data" / "ecc"
    for rel in [
        "maps/Floorplan/density.json",
        "maps/Floorplan/floorplan.json",
        "maps/place/density.json",
        "maps/place/congestion.json",
        "maps/CTS/density.json",
        "maps/CTS/congestion.json",
    ]:
        assert (foundation_dir / rel).exists(), rel

    floorplan_density = json.loads((foundation_dir / "maps" / "Floorplan" / "density.json").read_text(encoding="utf-8"))
    assert set(floorplan_density["maps"]) == {
        "allcell_density",
        "macro_density",
        "stdcell_density",
        "allcell_pin_density",
        "macro_pin_density",
        "stdcell_pin_density",
        "allnet_density",
        "local_net_density",
        "global_net_density",
    }
    assert [item["value"] for item in floorplan_density["maps"]["allcell_density"]["values"]] == [0.0, 0.0, 0.0, 0.0]

    floorplan_specific = json.loads((foundation_dir / "maps" / "Floorplan" / "floorplan.json").read_text(encoding="utf-8"))
    assert floorplan_specific["category"] == "floorplan"
    assert [item["value"] for item in floorplan_specific["maps"]["io_pin_density"]["values"]] == [0.0, 1.0, 0.0, 0.0]
    assert [item["value"] for item in floorplan_specific["maps"]["physical_only_cell_density"]["values"]] == [0.10416666666666667, 0.0, 0.0, 0.0]
    assert [item["value"] for item in floorplan_specific["maps"]["power_grid_density"]["values"]] == [0.125, 0.125, 0.0, 0.0]

    place_density = json.loads((foundation_dir / "maps" / "place" / "density.json").read_text(encoding="utf-8"))
    assert set(place_density["maps"]) == set(floorplan_density["maps"])
    assert place_density["maps"]["allcell_density"]["values"][0] == {"patch_id": 0, "row": 0, "col": 0, "value": 10.0}

    place_congestion = json.loads((foundation_dir / "maps" / "place" / "congestion.json").read_text(encoding="utf-8"))
    assert place_congestion["grid"] == {"source": "irt_gcell_info", "rows": 2, "cols": 2}
    assert [item["value"] for item in place_congestion["maps"]["union"]["values"]] == [3.0, 3.0, 3.0, 7.0]
    assert "strictly_aligned" not in json.dumps(place_congestion)

    cts_density = json.loads((foundation_dir / "maps" / "CTS" / "density.json").read_text(encoding="utf-8"))
    assert set(cts_density["maps"]) == set(place_density["maps"])
    assert cts_density["maps"]["allcell_density"]["values"][3] == {"patch_id": 3, "row": 1, "col": 1, "value": 103.0}

    quality = json.loads((foundation_dir / "quality.json").read_text(encoding="utf-8"))
    assert quality["availability"]["maps"]["Floorplan"] == "available"


def test_iccd_full_v1_drops_legacy_map_dirs_lutrudy_and_filler_from_allcell_density(tmp_path: Path):
    ws = _make_workspace(tmp_path)
    _write_sample_gcell_info(ws / "CTS_ecc")
    _write_csv(ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "density_map" / "cts_allcell_density.csv", [[0.4, 0.5], [0.6, 0.7]])
    _write_csv(ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "density_map" / "cts_macro_density.csv", [[0, 0.01], [0.02, 0]])
    _write_csv(ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "density_map" / "cts_stdcell_density.csv", [[0.1, 0.2], [0.3, 0.4]])
    _write_csv(ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "density_map" / "cts_allcell_pin_density.csv", [[10, 11], [12, 13]])
    _write_csv(ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "density_map" / "cts_macro_pin_density.csv", [[0, 1], [2, 0]])
    _write_csv(ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "density_map" / "cts_stdcell_pin_density.csv", [[1, 2], [3, 4]])
    _write_csv(ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "RUDY_map" / "cts_rudy_union.csv", [[1, 2], [3, 4]])
    _write_csv(ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "RUDY_map" / "cts_lut_rudy_union.csv", [[5, 6], [7, 8]])

    FoundationExtractor(ws, profile="iccd_full_v1").extract()

    foundation_dir = ws / "foundation_data" / "ecc"
    assert not (foundation_dir / "maps" / "canonical").exists()
    assert not (foundation_dir / "maps" / "raw").exists()

    cts_density = json.loads((foundation_dir / "maps" / "CTS" / "density.json").read_text(encoding="utf-8"))
    allcell = [item["value"] for item in cts_density["maps"]["allcell_density"]["values"]]
    stdcell = [item["value"] for item in cts_density["maps"]["stdcell_density"]["values"]]
    macro = [item["value"] for item in cts_density["maps"]["macro_density"]["values"]]
    assert macro == [0.0, 0.01, 0.02, 0.0]
    assert allcell == [0.1, 0.21000000000000002, 0.32, 0.4]
    allcell_pin = [item["value"] for item in cts_density["maps"]["allcell_pin_density"]["values"]]
    stdcell_pin = [item["value"] for item in cts_density["maps"]["stdcell_pin_density"]["values"]]
    macro_pin = [item["value"] for item in cts_density["maps"]["macro_pin_density"]["values"]]
    assert macro_pin == [0.0, 1.0, 2.0, 0.0]
    assert stdcell_pin == [1.0, 2.0, 3.0, 4.0]
    assert allcell_pin == [1.0, 3.0, 5.0, 4.0]

    cts_rudy = json.loads((foundation_dir / "maps" / "CTS" / "rudy.json").read_text(encoding="utf-8"))
    assert set(cts_rudy["maps"]) == {"rudy_union"}
    assert not (foundation_dir / "maps" / "CTS" / "ignored.json").exists()
    raw_refs = json.loads((foundation_dir / "raw_refs" / "artifacts.json").read_text(encoding="utf-8"))
    assert "lut_rudy" not in json.dumps(raw_refs)

def test_iccd_full_v1_marks_labels_missing_without_true_route_artifacts(tmp_path: Path):
    ws = _make_workspace(tmp_path, include_route_artifacts=False, include_route_maps=True)

    FoundationExtractor(ws, profile="iccd_full_v1").extract()

    foundation_dir = ws / "foundation_data" / "ecc"
    quality = json.loads((foundation_dir / "quality.json").read_text(encoding="utf-8"))
    summary = json.loads((foundation_dir / "summary.json").read_text(encoding="utf-8"))

    assert not (foundation_dir / "labels" / "route_patch_overflow.jsonl").exists()
    assert not (foundation_dir / "labels" / "candidate_qor_summary.json").exists()
    assert "route_patch_overflow" not in quality["availability"].get("labels", {})
    assert quality["availability"]["labels"]["route_native_demand_capacity"] == "missing"
    assert quality["null_reason"]["labels"]["route_native_demand_capacity"] == "missing_irt_space_router_native_demand_capacity_artifact"
    assert "route_patch_overflow_count" not in summary["labels"]
    assert summary["labels"]["route_native_demand_capacity_count"] == 0


def test_iccd_full_v1_keeps_native_missing_without_reconstructed_fallback(tmp_path: Path):
    ws = _make_workspace(tmp_path, include_native_demand_capacity=False)

    FoundationExtractor(ws, profile="iccd_full_v1").extract()

    foundation_dir = ws / "foundation_data" / "ecc"
    quality = json.loads((foundation_dir / "quality.json").read_text(encoding="utf-8"))
    patches = [json.loads(line) for line in (foundation_dir / "vectors" / "patches" / "route.jsonl").read_text().splitlines()]

    assert not (foundation_dir / "labels" / "route_patch_overflow.jsonl").exists()
    assert not (foundation_dir / "labels" / "route_reconstructed_congestion.jsonl").exists()
    assert not (foundation_dir / "labels" / "route_reconstructed_demand_capacity.jsonl").exists()
    native = (foundation_dir / "labels" / "route_native_demand_capacity.jsonl").read_text(encoding="utf-8")
    assert "route_true_overflow" not in patches[0]
    assert patches[0]["route_native_demand_capacity"]["union"] is None
    assert "route_reconstructed_demand_capacity" not in patches[0]
    assert "route_reconstructed_congestion" not in patches[0]
    assert patches[0]["route_demand_capacity"]["union"] is None
    assert not (foundation_dir / "labels" / "candidate_qor_summary.json").exists()
    assert native == ""
    assert quality["availability"]["labels"]["route_native_demand_capacity"] == "missing"
    assert quality["null_reason"]["labels"]["route_native_demand_capacity"] == "missing_irt_space_router_native_demand_capacity_artifact"
    assert "route_patch_overflow" not in quality["availability"].get("labels", {})
    assert "route_reconstructed_congestion" not in quality["availability"]["labels"]
    assert "route_reconstructed_demand_capacity" not in quality["availability"]["labels"]


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

    assert "stages" not in summary
    assert [item["name"] for item in summary["flow"]["steps"]] == ["place"]
    assert (foundation_dir / "vectors" / "instances" / "place.jsonl").exists()
    assert not (foundation_dir / "vectors" / "instances" / "route.jsonl").exists()
    assert not (foundation_dir / "raw_refs" / "artifacts.json").exists()
    assert manifest["options"]["stages"] == ["place"]
    assert manifest["options"]["include_raw_refs"] is False
    assert "raw_refs" not in manifest["artifacts"]
    assert evidence["raw_refs"] is None
    assert evidence["raw_refs_disabled"] is True
    assert "route_patch_overflow" not in quality["availability"].get("labels", {})


def test_iccd_full_v1_rejects_unknown_stage_filter(tmp_path: Path):
    ws = _make_workspace(tmp_path)

    try:
        FoundationExtractor(ws, profile="iccd_full_v1").extract(stages=["missing_stage"])
    except ValueError as exc:
        assert "unknown foundation extraction stage" in str(exc)
    else:
        raise AssertionError("expected unknown stage to fail")
