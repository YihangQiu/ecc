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
    assert all("availability" not in item for item in instances)
    assert any(item["identity"]["is_macro"] for item in instances)
    assert all("is_macro" not in item for item in instances)

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
    assert any(pin["identity"]["pin_name"] == "OUT" for pin in pins)
    assert any(wire["layer"] == "MET2" and wire["direction"] == "horizontal" for wire in wires)
    assert timing_paths
    timing_path = timing_paths[0]
    assert list(timing_path) == [
        "id",
        "stage",
        "path_key",
        "source",
        "identity",
        "analysis_context",
        "endpoints",
        "path_timing",
        "path_electrical",
        "path_points",
        "timing_edges",
        "wire_path_nodes",
        "path_spatial",
        "progressive_metadata",
        "coverage",
        "source_refs",
        "null_reason",
    ]
    assert timing_path["path_timing"]["slack"] == 1.0
    assert timing_path["path_timing"]["rank_in_stage"] == 0
    assert timing_path["path_timing"]["is_worst_path"] is True
    assert timing_path["path_timing"]["is_near_critical"] is True
    assert timing_path["path_timing"]["normalized_criticality"] is None
    assert timing_path["null_reason"]["path_timing"]["normalized_criticality"] == "constant_slack_range"
    assert timing_path["path_points"][0]["raw_name"] == "U1/A"
    assert timing_path["path_points"][0]["pin_key"] == "U1:A"
    assert timing_path["timing_edges"][0]["edge_kind"] == "cell_arc"
    assert timing_path["timing_edges"][0]["net_key"] is None
    assert timing_path["path_electrical"]["capacitance_sum"] == 0.5
    assert timing_path["path_electrical"]["max_slew"] == 0.6
    assert timing_path["path_electrical"]["resistance_sum"] == 1.5
    assert timing_path["wire_path_nodes"][0]["pin_key"] == "U1:A"
    assert timing_path["coverage"]["has_wire_path"] is True
    assert timing_path["path_spatial"]["anchor_source_policy"] == "prefer_pin_geometry_fallback_parent_instance"

    patches = [json.loads(line) for line in (foundation_dir / "vectors" / "patches" / "route.jsonl").read_text().splitlines()]
    patch0 = patches[0]
    assert list(patch0) == [
        "id",
        "stage",
        "patch_key",
        "source",
        "identity",
        "geometry",
        "local_density",
        "local_connectivity",
        "pre_route_estimators",
        "neighbor_context",
        "entity_refs",
        "timing_context",
        "electrical_context",
        "route_oracle",
        "label_refs",
        "drc_context",
        "progressive_metadata",
        "source_refs",
        "null_reason",
    ]
    assert "bbox" not in patch0
    assert "availability" not in patch0
    assert "route_true_overflow" not in patch0
    assert "route_reconstructed_congestion" not in patch0
    assert "route_native_demand_capacity" not in patch0
    assert "route_reconstructed_demand_capacity" not in patch0
    assert "route_demand_capacity" not in patch0
    assert "timing" not in patch0
    assert "electrical" not in patch0
    assert patch0["entity_refs"]["net_count"] >= 1
    assert patch0["route_oracle"]["wire_length_by_layer"]["MET2"] > 0
    native = patch0["route_oracle"]["native_demand_capacity"]
    assert native["horizontal_demand"] == 6.0
    assert native["horizontal_capacity"] == 3.0
    assert native["horizontal_overflow"] == 3.0
    assert native["vertical_overflow"] == 2.0
    assert native["union_overflow"] == 3.0
    assert native["union_utilization"] == 2.0
    assert native["tightness_class"] == "overflow"
    assert patch0["route_oracle"]["feature_role"] == "route_only_oracle"
    assert patch0["route_oracle"]["available_for_training_input"] is False
    assert patch0["timing_context"]["worst_slack_min"] == 1.0
    assert patch0["electrical_context"]["capacitance_sum"] == 0.5
    assert patch0["electrical_context"]["max_slew"] == 0.6

    drc_patches = [json.loads(line) for line in (foundation_dir / "vectors" / "patches" / "drc.jsonl").read_text().splitlines()]
    assert drc_patches[0]["drc_context"]["count"] == 2
    assert drc_patches[0]["drc_context"]["by_type"] == {"short": 2}
    assert drc_patches[-1]["drc_context"]["count"] == 1

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




def test_iccd_full_v1_orders_instance_record_fields_like_documented_schema(tmp_path: Path):
    ws = _make_workspace(tmp_path)

    FoundationExtractor(ws, profile="iccd_full_v1").extract(stages=["place"])

    row = json.loads((ws / "foundation_data" / "ecc" / "vectors" / "instances" / "place.jsonl").read_text().splitlines()[0])
    assert list(row) == [
        "id",
        "stage",
        "name",
        "source",
        "identity",
        "physical_state",
        "connectivity_summary",
        "patch_anchor",
        "progressive_metadata",
        "clock_tree",
        "route_analysis",
        "null_reason",
    ]

def test_iccd_full_v1_enriches_instances_from_def_components(tmp_path: Path):
    ws = _make_workspace(tmp_path)
    _write_text(
        ws / "place_dreamplace" / "output" / "gcd_place.def",
        """
VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN gcd ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 200 200 ) ;
COMPONENTS 2 ;
- U1 DFFHQNX1H7L + PLACED ( 10 20 ) N ;
- U2 BUFX1P4H7L + PLACED ( 50 60 ) FS ;
END COMPONENTS
NETS 1 ;
- clk ( U1 CK ) ( U2 A ) ;
END NETS
END DESIGN
""".strip()
        + "\n",
    )
    _write_json(
        ws / "place_dreamplace" / "output" / "gcd_place.json",
        {
            "design name": "gcd",
            "diearea": {"path": [[0, 0], [200, 0], [200, 200], [0, 200], [0, 0]]},
            "layerInfo": [{"id": 0, "layername": "cell"}],
            "data": [
                {
                    "type": "group",
                    "struct name": "Instance_U1",
                    "children": [
                        {"type": "box", "layer": 0, "path": [[10, 20], [30, 20], [30, 40], [10, 40], [10, 20]]}
                    ],
                },
                {
                    "type": "group",
                    "struct name": "Instance_U2",
                    "children": [
                        {"type": "box", "layer": 0, "path": [[50, 60], [60, 60], [60, 70], [50, 70], [50, 60]]}
                    ],
                },
            ],
        },
    )

    FoundationExtractor(ws, profile="iccd_full_v1").extract(stages=["place"])

    foundation_dir = ws / "foundation_data" / "ecc"
    instances = [
        json.loads(line)
        for line in (foundation_dir / "vectors" / "instances" / "place.jsonl").read_text().splitlines()
    ]
    first = instances[0]
    assert first["identity"]["instance_key"] == "U1"
    assert first["identity"]["master"] == "DFFHQNX1H7L"
    assert first["identity"]["cell_class"] == "sequential"
    assert first["physical_state"]["origin"] == {"x": 10.0, "y": 20.0}
    assert first["physical_state"]["orientation"] == "N"
    assert first["physical_state"]["placement_status"] == "placed"
    assert "master" not in first
    assert "orientation" not in first


def test_iccd_full_v1_uses_semantic_null_for_floorplan_unplaced_stdcells(tmp_path: Path):
    ws = _make_workspace(tmp_path)
    _write_text(
        ws / "Floorplan_ecc" / "output" / "gcd_Floorplan.def",
        """
VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN gcd ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 200 200 ) ;
COMPONENTS 1 ;
- U1 NAND2 ;
END COMPONENTS
NETS 1 ;
- n1 ( U1 A ) ;
END NETS
END DESIGN
""".strip()
        + "\n",
    )
    _write_json(
        ws / "Floorplan_ecc" / "output" / "gcd_Floorplan.json",
        {
            "design name": "gcd",
            "diearea": {"path": [[0, 0], [200, 0], [200, 200], [0, 200], [0, 0]]},
            "layerInfo": [{"id": 0, "layername": "cell"}],
            "data": [
                {
                    "type": "group",
                    "struct name": "Instance_U1",
                    "children": [
                        {"type": "box", "layer": 0, "path": [[0, 0], [0, 0], [0, 0], [0, 0], [0, 0]]}
                    ],
                }
            ],
        },
    )

    FoundationExtractor(ws, profile="iccd_full_v1").extract(stages=["Floorplan"])

    row = json.loads((ws / "foundation_data" / "ecc" / "vectors" / "instances" / "Floorplan.jsonl").read_text())
    assert row["physical_state"]["placement_status"] == "unplaced"
    assert row["physical_state"]["origin"] is None
    assert row["physical_state"]["bbox"] is None
    assert row["physical_state"]["center"] is None
    assert row["physical_state"]["area"] is None
    assert row["null_reason"]["physical_state_bbox"] == "not_available_before_placement"


def test_iccd_full_v1_adds_instance_patch_anchor(tmp_path: Path):
    ws = _make_workspace(tmp_path)
    _write_csv(ws / "place_dreamplace" / "feature" / "gcell_patch_map" / "density_map" / "place_allcell_density.csv", [[0.5, 0.0], [0.0, 0.0]])
    _write_csv(ws / "place_dreamplace" / "feature" / "gcell_patch_map" / "density_map" / "place_allcell_pin_density.csv", [[2.0, 0.0], [0.0, 0.0]])
    _write_csv(ws / "place_dreamplace" / "feature" / "gcell_patch_map" / "RUDY_map" / "place_rudy_union.csv", [[0.01, 0.0], [0.0, 0.0]])
    _write_csv(ws / "place_dreamplace" / "feature" / "egr_congestion_map" / "place_egr_union_overflow.csv", [[3.0, 0.0], [0.0, 0.0]])
    for path in (ws / "place_dreamplace" / "feature" / "gcell_patch_map" / "density_map").glob("place_*density.csv"):
        if path.name not in {"place_allcell_density.csv", "place_allcell_pin_density.csv"}:
            path.unlink()
    for path in (ws / "place_dreamplace" / "feature" / "gcell_patch_map" / "RUDY_map").glob("place_*rudy*.csv"):
        if path.name != "place_rudy_union.csv":
            path.unlink()

    FoundationExtractor(ws, profile="iccd_full_v1").extract(stages=["place"])

    record = json.loads((ws / "foundation_data" / "ecc" / "vectors" / "instances" / "place.jsonl").read_text().splitlines()[0])
    assert record["patch_anchor"]["primary_patch_id"] == 0
    assert record["patch_anchor"]["overlap_patch_ids"] == [0]
    assert record["physical_state"]["patch_id"] == 0
    assert record["physical_state"]["overlap_patch_ids"] == [0]
    assert record["patch_anchor"]["local_cell_density"] == 0.5
    assert record["patch_anchor"]["local_pin_density"] == 2.0
    assert record["patch_anchor"]["local_rudy"] == 0.01
    assert record["patch_anchor"]["local_egr_overflow"] == 3.0


def test_iccd_full_v1_adds_instance_connectivity_summary(tmp_path: Path):
    ws = _make_workspace(tmp_path)
    _write_text(
        ws / "place_dreamplace" / "output" / "gcd_place.def",
        """
VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN gcd ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 240 200 ) ;
COMPONENTS 3 ;
- U1 DFFHQNX1H7L + PLACED ( 10 20 ) N ;
- U2 BUFX1P4H7L + PLACED ( 180 20 ) N ;
- U3 NAND2 + PLACED ( 10 140 ) N ;
END COMPONENTS
NETS 2 ;
- clk ( U1 CK ) ( U2 A ) ( U3 A ) ;
- data ( U1 D ) ( U2 Y ) ;
END NETS
END DESIGN
""".strip()
        + "\n",
    )
    _write_json(
        ws / "place_dreamplace" / "output" / "gcd_place.json",
        {
            "design name": "gcd",
            "diearea": {"path": [[0, 0], [240, 0], [240, 200], [0, 200], [0, 0]]},
            "layerInfo": [{"id": 0, "layername": "cell"}],
            "data": [
                {"type": "group", "struct name": "Instance_U1", "children": [{"type": "box", "layer": 0, "path": [[10, 20], [30, 20], [30, 40], [10, 40], [10, 20]]}]},
                {"type": "group", "struct name": "Instance_U2", "children": [{"type": "box", "layer": 0, "path": [[180, 20], [200, 20], [200, 40], [180, 40], [180, 20]]}]},
                {"type": "group", "struct name": "Instance_U3", "children": [{"type": "box", "layer": 0, "path": [[10, 140], [30, 140], [30, 160], [10, 160], [10, 140]]}]},
            ],
        },
    )

    FoundationExtractor(ws, profile="iccd_full_v1").extract(stages=["place"])

    rows = [json.loads(line) for line in (ws / "foundation_data" / "ecc" / "vectors" / "instances" / "place.jsonl").read_text().splitlines()]
    record = next(row for row in rows if row["identity"]["instance_key"] == "U1")
    summary = record["connectivity_summary"]
    assert summary["pin_count"] == 2
    assert summary["connected_net_count"] == 2
    assert summary["clock_pin_count"] == 1
    assert summary["max_net_degree"] >= 2
    assert summary["sum_connected_hpwl"] is not None
    assert summary["max_connected_hpwl"] is not None
    assert summary["cross_patch_net_count"] >= 1
    assert "route_wire_length" not in summary
    assert "rudy" not in summary
    assert "egr_overflow" not in summary


def test_iccd_full_v1_tracks_cts_inserted_instances(tmp_path: Path):
    ws = _make_workspace(tmp_path)
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
- U1 DFFHQNX1H7L + PLACED ( 10 20 ) N ;
END COMPONENTS
NETS 1 ;
- clk ( U1 CK ) ;
END NETS
END DESIGN
""".strip()
        + "\n",
    )
    _write_json(
        ws / "place_dreamplace" / "output" / "gcd_place.json",
        {
            "design name": "gcd",
            "diearea": {"path": [[0, 0], [200, 0], [200, 200], [0, 200], [0, 0]]},
            "layerInfo": [{"id": 0, "layername": "cell"}],
            "data": [
                {"type": "group", "struct name": "Instance_U1", "children": [{"type": "box", "layer": 0, "path": [[10, 20], [30, 20], [30, 40], [10, 40], [10, 20]]}]}
            ],
        },
    )
    _write_text(
        ws / "CTS_ecc" / "output" / "gcd_CTS.def",
        """
VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN gcd ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 200 200 ) ;
COMPONENTS 2 ;
- U1 DFFHQNX1H7L + PLACED ( 12 22 ) N ;
- clk_leaf_0_0_buf BUFX1P4H7L + PLACED ( 80 80 ) N ;
END COMPONENTS
NETS 2 ;
- clk ( clk_leaf_0_0_buf A ) ;
- clk_leaf ( clk_leaf_0_0_buf Y ) ( U1 CK ) ;
END NETS
END DESIGN
""".strip()
        + "\n",
    )
    _write_json(
        ws / "CTS_ecc" / "output" / "gcd_CTS.json",
        {
            "design name": "gcd",
            "diearea": {"path": [[0, 0], [200, 0], [200, 200], [0, 200], [0, 0]]},
            "layerInfo": [{"id": 0, "layername": "cell"}],
            "data": [
                {"type": "group", "struct name": "Instance_U1", "children": [{"type": "box", "layer": 0, "path": [[12, 22], [32, 22], [32, 42], [12, 42], [12, 22]]}]},
                {"type": "group", "struct name": "clk_leaf_0_0_buf", "children": [{"type": "box", "layer": 0, "path": [[80, 80], [90, 80], [90, 90], [80, 90], [80, 80]]}]},
            ],
        },
    )

    FoundationExtractor(ws, profile="iccd_full_v1").extract(stages=["place", "CTS"])

    cts_instances = [json.loads(line) for line in (ws / "foundation_data" / "ecc" / "vectors" / "instances" / "CTS.jsonl").read_text().splitlines()]
    cts_buf = next(item for item in cts_instances if item["name"] == "clk_leaf_0_0_buf")
    assert cts_buf["progressive_metadata"]["created_stage"] == "CTS"
    assert cts_buf["progressive_metadata"]["created_stage_source"] == "first_observed"
    assert cts_buf["progressive_metadata"]["exists_in_prev_stage"] is False
    assert cts_buf["progressive_metadata"]["exists_in_place"] is False
    assert cts_buf["clock_tree"]["is_clock_tree_node"] is True
    assert cts_buf["clock_tree"]["clock_tree_role"] in {"root_buffer", "internal_buffer", "leaf_buffer", "clock_buffer"}
    moved = next(item for item in cts_instances if item["identity"]["instance_key"] == "U1")
    assert moved["progressive_metadata"]["exists_in_prev_stage"] is True
    assert moved["progressive_metadata"]["moved_from_prev_stage"] is True
    assert moved["progressive_metadata"]["dx_from_prev_stage"] == 2.0
    assert moved["progressive_metadata"]["dy_from_prev_stage"] == 2.0


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
    assert "route_native_demand_capacity" not in patches[0]
    assert patches[0]["route_oracle"]["native_demand_capacity"]["union_overflow"] is None
    assert "route_reconstructed_demand_capacity" not in patches[0]
    assert "route_reconstructed_congestion" not in patches[0]
    assert "route_demand_capacity" not in patches[0]
    assert patches[0]["label_refs"]["label_source_status"] == "missing"
    assert patches[0]["null_reason"]["route_oracle"] == "missing_router_native_route_overflow_artifact"
    assert not (foundation_dir / "labels" / "candidate_qor_summary.json").exists()
    assert native == ""
    assert quality["availability"]["labels"]["route_native_demand_capacity"] == "missing"
    assert quality["null_reason"]["labels"]["route_native_demand_capacity"] == "missing_irt_space_router_native_demand_capacity_artifact"
    assert "route_patch_overflow" not in quality["availability"].get("labels", {})
    assert "route_reconstructed_congestion" not in quality["availability"]["labels"]
    assert "route_reconstructed_demand_capacity" not in quality["availability"]["labels"]


def test_iccd_full_v1_patch_records_follow_vec_patches_schema(tmp_path: Path):
    ws = _make_workspace(tmp_path)

    FoundationExtractor(ws, profile="iccd_full_v1").extract()

    foundation_dir = ws / "foundation_data" / "ecc"
    place_patches = [
        json.loads(line)
        for line in (foundation_dir / "vectors" / "patches" / "place.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    route_patches = [
        json.loads(line)
        for line in (foundation_dir / "vectors" / "patches" / "route.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    place0 = place_patches[0]
    route0 = route_patches[0]

    assert list(place0) == [
        "id",
        "stage",
        "patch_key",
        "source",
        "identity",
        "geometry",
        "local_density",
        "local_connectivity",
        "pre_route_estimators",
        "neighbor_context",
        "entity_refs",
        "timing_context",
        "electrical_context",
        "route_oracle",
        "label_refs",
        "drc_context",
        "progressive_metadata",
        "source_refs",
        "null_reason",
    ]
    legacy_flat_fields = {
        "patch_id",
        "row",
        "col",
        "instance_count",
        "instance_area",
        "macro_area",
        "net_count",
        "pin_count",
        "wire_length_by_layer",
        "route_native_demand_capacity",
        "route_demand_capacity",
        "drc",
        "timing",
        "electrical",
        "cell_density",
        "pin_density",
        "net_density",
        "macro_density",
        "rudy_congestion",
        "margin_horizontal",
        "margin_vertical",
        "congestion_horizontal",
        "congestion_vertical",
        "congestion_union",
    }
    assert not (set(place0) & legacy_flat_fields)
    assert place0["local_density"] == {
        "feature_role": "progressive_input",
        "available_for_training_input": True,
        "instance_count_center": 2,
        "instance_count_overlap": 2,
        "stdcell_count_center": 1,
        "macro_count_overlap": 1,
        "physical_only_count_overlap": 0,
        "stdcell_area_overlap": 200.0,
        "macro_area_overlap": 1500.0,
        "instance_area_overlap": 1700.0,
        "cell_density": 10.0,
        "macro_density": 0.0,
        "pin_count_anchor": 1,
        "pin_count_overlap": 0,
        "pin_density": 20.0,
        "net_density": 30.0,
        "wire_length": 0.0,
        "wire_length_by_layer": {},
        "via_count": 0,
        "source": "maps_and_vectors",
    }
    assert place0["local_connectivity"]["net_count_anchor"] == 1
    assert place0["local_connectivity"]["cross_patch_net_count"] == 1
    assert place0["local_connectivity"]["signal_net_count"] == 1
    assert place0["local_connectivity"]["local_hpwl_sum"] == 215.0
    assert place0["pre_route_estimators"] == {
        "feature_role": "progressive_input",
        "available_for_training_input": True,
        "rudy_horizontal": None,
        "rudy_vertical": None,
        "rudy_union": 50.0,
        "egr_overflow_horizontal": 1.0,
        "egr_overflow_vertical": 3.0,
        "egr_overflow_union": 3.0,
        "margin_horizontal": None,
        "margin_vertical": None,
        "source": "canonical_maps",
    }
    assert place0["neighbor_context"]["feature_role"] == "progressive_input"
    assert place0["neighbor_context"]["available_for_training_input"] is True
    assert place0["neighbor_context"]["window_3x3_patch_ids"] == [0, 1, 2, 3]
    assert place0["neighbor_context"]["window_3x3_valid_count"] == 4
    assert place0["neighbor_context"]["edge_position"] == "corner"
    assert place0["neighbor_context"]["window_3x3_cell_density_mean"] == 11.5
    assert place0["neighbor_context"]["window_3x3_pin_count_sum"] == 2
    assert place0["entity_refs"]["anchor_semantics"] == "primary_patch_or_center"
    assert place0["entity_refs"]["overlap_semantics"] == "bbox_or_segment_intersection"
    assert place0["entity_refs"]["instance_count"] == 2
    assert place0["entity_refs"]["pin_count"] == 1
    assert place0["entity_refs"]["net_count"] == 1
    assert place0["entity_refs"]["refs_truncated"] is False
    assert place0["entity_refs"]["sample_instance_keys"] == ["U1", "SRAM0"]
    assert place0["timing_context"]["feature_role"] == "stage_qor_context"
    assert place0["timing_context"]["available_for_training_input"] is True
    assert place0["timing_context"]["critical_path_count"] == 0
    assert place0["timing_context"]["worst_slack_min"] is None
    assert place0["electrical_context"]["feature_role"] == "stage_qor_context"
    assert place0["electrical_context"]["scope"] == "patch"
    assert place0["electrical_context"]["availability"] == "missing"
    assert place0["route_oracle"] is None
    assert place0["label_refs"]["label_source_status"] == "missing"
    assert place0["drc_context"]["feature_role"] == "route_or_drc_analysis"
    assert place0["drc_context"]["available_for_training_input"] is False
    assert place0["progressive_metadata"]["available_from"] == "Floorplan"
    assert place0["progressive_metadata"]["stage_order_index"] == 1
    assert place0["progressive_metadata"]["is_progressive_input_stage"] is True
    assert place0["progressive_metadata"]["is_route_oracle_stage"] is False
    assert "route_oracle" not in place0["progressive_metadata"]["input_blocks"]
    assert place0["progressive_metadata"]["oracle_blocks"] == []
    assert place0["source_refs"]["stage_def"] == "place_dreamplace/output/gcd_place.def"
    assert place0["source_refs"]["density_maps"] == "maps/place/density.json"
    assert place0["source_refs"]["route_label_definition"] is None
    assert place0["null_reason"]["route_oracle"] == "not_route_stage"

    native = route0["route_oracle"]["native_demand_capacity"]
    assert route0["route_oracle"]["feature_role"] == "route_only_oracle"
    assert route0["route_oracle"]["wire_length"] > 0
    assert native["horizontal_demand"] == 6.0
    assert native["horizontal_capacity"] == 3.0
    assert native["horizontal_overflow"] == 3.0
    assert native["horizontal_utilization"] == 2.0
    assert native["vertical_demand"] == 4.0
    assert native["vertical_capacity"] == 2.0
    assert native["vertical_overflow"] == 2.0
    assert native["vertical_utilization"] == 2.0
    assert native["union_overflow"] == 3.0
    assert native["union_utilization"] == 2.0
    assert native["tightness_class"] == "overflow"
    assert route0["label_refs"]["route_native_demand_capacity"] == "labels/route_native_demand_capacity.jsonl#patch_id=0"
    assert route0["label_refs"]["label_source_status"] == "available"
    assert route0["progressive_metadata"]["is_progressive_input_stage"] is False
    assert route0["progressive_metadata"]["is_route_oracle_stage"] is True
    assert route0["progressive_metadata"]["oracle_blocks"] == ["route_oracle"]
    assert route0["source_refs"]["route_label_definition"] == "route_oracle.native_demand_capacity.union_overflow=max(horizontal_overflow,vertical_overflow); union_utilization=max(horizontal_utilization,vertical_utilization); tightness_class={overflow,near_capacity,relaxed,unknown}"


def test_iccd_full_v1_patch_records_compute_progressive_deltas_and_quality_stats(tmp_path: Path):
    ws = _make_workspace(tmp_path)
    _write_sample_gcell_info(ws / "CTS_ecc")
    _write_sample_egr_demand_capacity(ws / "CTS_ecc")
    _write_csv(ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "density_map" / "cts_allcell_density.csv", [[100, 101], [102, 103]])
    _write_csv(ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "density_map" / "cts_allcell_pin_density.csv", [[104, 105], [106, 107]])
    _write_csv(ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "density_map" / "cts_allnet_density.csv", [[108, 109], [110, 111]])
    _write_csv(ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "density_map" / "cts_macro_density.csv", [[0, 0], [0, 0]])
    _write_csv(ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "density_map" / "cts_stdcell_density.csv", [[100, 101], [102, 103]])
    _write_csv(ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "density_map" / "cts_stdcell_pin_density.csv", [[104, 105], [106, 107]])
    _write_csv(ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "density_map" / "cts_macro_pin_density.csv", [[0, 0], [0, 0]])
    _write_csv(ws / "CTS_ecc" / "feature" / "gcell_patch_map" / "RUDY_map" / "cts_rudy_union.csv", [[110, 111], [112, 113]])

    FoundationExtractor(ws, profile="iccd_full_v1").extract()

    foundation_dir = ws / "foundation_data" / "ecc"
    place0 = json.loads((foundation_dir / "vectors" / "patches" / "place.jsonl").read_text(encoding="utf-8").splitlines()[0])
    cts0 = json.loads((foundation_dir / "vectors" / "patches" / "CTS.jsonl").read_text(encoding="utf-8").splitlines()[0])
    route0 = json.loads((foundation_dir / "vectors" / "patches" / "route.jsonl").read_text(encoding="utf-8").splitlines()[0])
    drc0 = json.loads((foundation_dir / "vectors" / "patches" / "drc.jsonl").read_text(encoding="utf-8").splitlines()[0])
    quality = json.loads((foundation_dir / "quality.json").read_text(encoding="utf-8"))

    assert place0["progressive_metadata"]["density_delta_from_prev_stage"] == 10.0
    assert place0["progressive_metadata"]["pin_count_delta_from_prev_stage"] == -1.0
    assert place0["progressive_metadata"]["rudy_delta_from_prev_stage"] is None
    assert place0["progressive_metadata"]["egr_overflow_delta_from_prev_stage"] is None
    assert cts0["progressive_metadata"]["density_delta_from_prev_stage"] == 90.0
    assert cts0["progressive_metadata"]["pin_count_delta_from_prev_stage"] == -1.0
    assert cts0["progressive_metadata"]["rudy_delta_from_prev_stage"] == 60.0
    assert cts0["progressive_metadata"]["egr_overflow_delta_from_prev_stage"] == 0.0

    for block_name in (
        "local_density",
        "local_connectivity",
        "pre_route_estimators",
        "neighbor_context",
        "timing_context",
        "electrical_context",
        "drc_context",
    ):
        assert route0[block_name]["available_for_training_input"] is False
    assert route0["route_oracle"]["available_for_training_input"] is False
    assert drc0["progressive_metadata"]["is_progressive_input_stage"] is False
    assert drc0["progressive_metadata"]["input_blocks"] == []
    for block_name in (
        "local_density",
        "local_connectivity",
        "pre_route_estimators",
        "neighbor_context",
        "timing_context",
        "electrical_context",
        "drc_context",
    ):
        assert drc0[block_name]["available_for_training_input"] is False

    patch_quality = quality["patches"]
    assert patch_quality["rows_by_stage"] == {"Floorplan": 4, "place": 4, "CTS": 4, "route": 4, "drc": 4}
    assert patch_quality["schema_coverage_by_stage"]["route"]["complete_records"] == 4
    assert patch_quality["pre_route_estimators_availability_by_stage"]["place"] == {"available": 4, "missing": 0, "not_applicable": 0}
    assert patch_quality["pre_route_estimators_availability_by_stage"]["route"] == {"available": 0, "missing": 0, "not_applicable": 4}
    assert patch_quality["route_label_availability"] == {"available": 4, "missing": 0, "partial": 0}
    assert patch_quality["route_oracle_tightness_class_distribution"] == {"overflow": 2, "near_capacity": 0, "relaxed": 2, "unknown": 0}
    assert patch_quality["refs_truncated_count_by_stage"]["route"] == 0
    assert patch_quality["timing_context_availability_by_stage"]["route"] == {"available": 1, "missing": 3, "not_applicable": 0}
    assert patch_quality["electrical_context_availability_by_stage"]["route"] == {"available": 1, "missing": 3, "not_applicable": 0}
    assert patch_quality["drc_context_availability_by_stage"]["drc"]["available"] == 4
    null_reason_counts = {item["reason"]: item["count"] for item in patch_quality["null_reason_topk"]}
    assert null_reason_counts["route_oracle=not_route_stage"] == 16


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


def test_iccd_full_v1_writes_canonical_pin_records_without_flat_fields(tmp_path: Path):
    ws = _make_workspace(tmp_path)
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
- OUT + NET n1 + DIRECTION OUTPUT + USE SIGNAL + LAYER MET2 ( -5 -5 ) ( 5 5 ) + PLACED ( 180 50 ) N ;
END PINS
NETS 1 ;
- n1 ( U1 A ) ( PIN OUT ) ;
END NETS
END DESIGN
""".strip()
        + "\n",
    )

    FoundationExtractor(ws, profile="iccd_full_v1").extract(stages=["place"])

    rows = [
        json.loads(line)
        for line in (ws / "foundation_data" / "ecc" / "vectors" / "pins" / "place.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    io_pin = next(row for row in rows if row["pin_key"] == "PIN:OUT")
    inst_pin = next(row for row in rows if row["pin_key"] == "U1:A")

    assert list(io_pin) == [
        "id",
        "stage",
        "pin_key",
        "source",
        "identity",
        "electrical_context",
        "parent_instance",
        "geometry",
        "connectivity_context",
        "timing_context",
        "patch_anchor",
        "route_context",
        "progressive_metadata",
        "source_refs",
        "null_reason",
    ]
    assert {"instance", "net", "pin_name", "direction", "bbox", "center", "layer", "patch_id"}.isdisjoint(io_pin)
    assert io_pin["identity"] == {
        "pin_key": "PIN:OUT",
        "pin_kind": "io_port",
        "instance": "PIN",
        "parent_instance_key": None,
        "parent_master": None,
        "pin_name": "OUT",
        "full_name": "PIN/OUT",
        "net": "n1",
        "net_key": "n1",
        "is_io": True,
        "is_macro_pin": False,
        "classification_source": "def_section",
    }
    assert io_pin["electrical_context"]["direction"] == "OUTPUT"
    assert io_pin["electrical_context"]["use"] == "SIGNAL"
    assert io_pin["electrical_context"]["direction_source"] == "def_pin_direction"
    assert io_pin["geometry"]["geometry_status"] == "exact"
    assert io_pin["geometry"]["anchor_source"] == "io_pin_shape"
    assert io_pin["geometry"]["bbox"] == {"llx": 175.0, "lly": 45.0, "urx": 185.0, "ury": 55.0}
    assert io_pin["geometry"]["center"] == {"x": 180.0, "y": 50.0}
    assert io_pin["geometry"]["layers"] == ["MET2"]
    assert io_pin["patch_anchor"]["anchor_source"] == "exact_pin_geometry"
    assert io_pin["route_context"] is None
    assert io_pin["progressive_metadata"]["route_only_oracle"] is False
    assert inst_pin["parent_instance"]["instance_key"] == "U1"
    assert inst_pin["geometry"]["geometry_status"] == "fallback_to_instance_anchor"
    assert inst_pin["geometry"]["anchor_source"] == "parent_instance_center"
    assert inst_pin["geometry"]["bbox"] is None
    assert inst_pin["null_reason"]["geometry_bbox"] == "missing_lef_pin_shape"
    assert inst_pin["connectivity_context"]["net_degree"] == 2
    assert inst_pin["connectivity_context"]["same_net_pin_count"] == 2


def test_iccd_full_v1_pins_use_lef_geometry_electrical_context_and_route_attribution(tmp_path: Path):
    ws = _make_workspace(tmp_path)
    _write_json(
        ws / "home" / "parameters.json",
        {
            "PDK": "unit-test",
            "PDK Root": str(ws / "pdk"),
            "Design": "gcd",
            "Core": {"Utilitization": 0.5},
        },
    )
    _write_text(
        ws / "pdk" / "unit.lef",
        """
VERSION 5.8 ;
MACRO NAND2
  CLASS CORE ;
  SIZE 20 BY 20 ;
  PIN A
    DIRECTION INPUT ;
    USE SIGNAL ;
    PORT
      LAYER MET2 ;
        RECT 1 2 5 6 ;
    END
  END A
  PIN Y
    DIRECTION OUTPUT ;
    USE SIGNAL ;
    PORT
      LAYER MET2 ;
        RECT 10 10 14 14 ;
    END
  END Y
END NAND2
END LIBRARY
""".strip()
        + "\n",
    )
    _write_text(
        ws / "place_dreamplace" / "output" / "gcd_place.def",
        """
VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN gcd ;
UNITS DISTANCE MICRONS 1 ;
DIEAREA ( 0 0 ) ( 200 200 ) ;
COMPONENTS 2 ;
- U1 NAND2 + PLACED ( 10 20 ) N ;
- U2 NAND2 + PLACED ( 40 20 ) N ;
END COMPONENTS
PINS 1 ;
- OUT + NET n1 + DIRECTION OUTPUT + USE SIGNAL + LAYER MET2 ( -5 -5 ) ( 5 5 ) + PLACED ( 180 50 ) N ;
END PINS
NETS 2 ;
- n1 ( U1 A ) ( U2 A ) ( PIN OUT ) ;
- n2 ( U1 Y ) ( U2 Y ) ;
END NETS
END DESIGN
""".strip()
        + "\n",
    )
    _write_text(
        ws / "route_ecc" / "output" / "gcd_route.def",
        """
VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN gcd ;
UNITS DISTANCE MICRONS 1 ;
DIEAREA ( 0 0 ) ( 200 200 ) ;
COMPONENTS 2 ;
- U1 NAND2 + PLACED ( 10 20 ) N ;
- U2 NAND2 + PLACED ( 40 20 ) N ;
END COMPONENTS
PINS 1 ;
- OUT + NET n1 + DIRECTION OUTPUT + USE SIGNAL + LAYER MET2 ( -5 -5 ) ( 5 5 ) + PLACED ( 180 50 ) N ;
END PINS
NETS 2 ;
- n1 ( U1 A ) ( U2 A ) ( PIN OUT )
  + ROUTED MET2 ( 11 22 ) ( 90 * )
    NEW MET2 ( 42 22 ) ( 100 * )
  ;
- n2 ( U1 Y ) ( U2 Y )
  + ROUTED MET3 ( 22 32 ) ( * 120 )
  ;
END NETS
END DESIGN
""".strip()
        + "\n",
    )
    _write_sample_gcell_info(ws / "route_ecc")
    _write_text(
        ws / "route_ecc" / "data" / "rt" / "space_router" / "route_native_demand_capacity_final.jsonl",
        "\n".join(
            [
                json.dumps({"row": 0, "col": 0, "gcell": {"x": 0, "y": 0}, "layer": "MET2", "direction": "horizontal", "demand": 6, "capacity": 3, "demand_capacity": 3, "utilization": 2, "overflow": 3, "source": "irt_space_router_native"}),
                json.dumps({"row": 0, "col": 1, "gcell": {"x": 1, "y": 0}, "layer": "MET2", "direction": "horizontal", "demand": 2, "capacity": 3, "demand_capacity": -1, "utilization": 0.67, "overflow": 0, "source": "irt_space_router_native"}),
            ]
        )
        + "\n",
    )
    _write_json(
        ws / "drc_ecc" / "data" / "drc" / "violation_map.json",
        [{"type": "short", "layer": "MET2", "bbox": {"llx": 10, "lly": 20, "urx": 20, "ury": 30}, "count": 2}],
    )

    FoundationExtractor(ws, profile="iccd_full_v1").extract(stages=["place", "route", "drc"])

    foundation_dir = ws / "foundation_data" / "ecc"
    place_rows = [json.loads(line) for line in (foundation_dir / "vectors" / "pins" / "place.jsonl").read_text().splitlines()]
    route_rows = [json.loads(line) for line in (foundation_dir / "vectors" / "pins" / "route.jsonl").read_text().splitlines()]
    u1_a = next(row for row in place_rows if row["pin_key"] == "U1:A")
    u1_y = next(row for row in place_rows if row["pin_key"] == "U1:Y")
    route_u1_a = next(row for row in route_rows if row["pin_key"] == "U1:A")

    assert u1_a["geometry"]["geometry_status"] == "exact"
    assert u1_a["geometry"]["anchor_source"] == "lef_pin_shape"
    assert u1_a["geometry"]["bbox"] == {"llx": 11.0, "lly": 22.0, "urx": 15.0, "ury": 26.0}
    assert u1_a["geometry"]["layers"] == ["MET2"]
    assert u1_a["electrical_context"]["direction"] == "INPUT"
    assert u1_a["electrical_context"]["direction_source"] == "lef_pin_direction"
    assert u1_a["connectivity_context"]["pin_role"] == "sink"
    assert u1_y["electrical_context"]["direction"] == "OUTPUT"
    assert u1_y["connectivity_context"]["pin_role"] == "driver"
    assert u1_a["patch_anchor"]["nearby_pin_count"] >= 2
    assert u1_a["patch_anchor"]["nearby_io_pin_count"] >= 0
    assert u1_a["source_refs"]["lef"].endswith("unit.lef")
    assert u1_a["source_refs"]["lef_macro"] == "NAND2"
    assert u1_a["source_refs"]["lef_pin"] == "A"
    assert "geometry_bbox" not in u1_a["null_reason"]

    assert route_u1_a["route_context"]["route_only_oracle"] is True
    assert route_u1_a["route_context"]["nearby_wire_count"] >= 1
    assert route_u1_a["route_context"]["nearby_drc_count"] == 2
    assert route_u1_a["route_context"]["local_final_overflow"] == 3.0
    assert route_u1_a["route_context"]["net_detour_ratio"] is not None
    assert route_u1_a["route_context"]["source"] == "route_ecc/output/gcd_route.def"


def test_iccd_full_v1_pin_progressive_and_route_leakage_guard(tmp_path: Path):
    ws = _make_workspace(tmp_path)
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
- U1 DFFHQNX1H7L + PLACED ( 10 20 ) N ;
END COMPONENTS
NETS 1 ;
- clk ( U1 CK ) ;
END NETS
END DESIGN
""".strip()
        + "\n",
    )
    _write_text(
        ws / "CTS_ecc" / "output" / "gcd_CTS.def",
        """
VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN gcd ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 200 200 ) ;
COMPONENTS 2 ;
- U1 DFFHQNX1H7L + PLACED ( 12 22 ) N ;
- clk_leaf_0_0_buf BUFX1P4H7L + PLACED ( 80 80 ) N ;
END COMPONENTS
NETS 2 ;
- clk ( clk_leaf_0_0_buf A ) ;
- clk_leaf ( clk_leaf_0_0_buf Y ) ( U1 CK ) ;
END NETS
END DESIGN
""".strip()
        + "\n",
    )
    _write_json(
        ws / "CTS_ecc" / "output" / "gcd_CTS.json",
        {
            "design name": "gcd",
            "diearea": {"path": [[0, 0], [200, 0], [200, 200], [0, 200], [0, 0]]},
            "layerInfo": [{"id": 0, "layername": "cell"}],
            "data": [
                {"type": "group", "struct name": "Instance_U1", "children": [{"type": "box", "layer": 0, "path": [[12, 22], [32, 22], [32, 42], [12, 42], [12, 22]]}]},
                {"type": "group", "struct name": "clk_leaf_0_0_buf", "children": [{"type": "box", "layer": 0, "path": [[80, 80], [90, 80], [90, 90], [80, 90], [80, 80]]}]},
            ],
        },
    )

    _write_text(
        ws / "route_ecc" / "output" / "gcd_route.def",
        """
VERSION 5.8 ;
DIVIDERCHAR "/" ;
BUSBITCHARS "[]" ;
DESIGN gcd ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 ) ( 200 200 ) ;
COMPONENTS 2 ;
- U1 DFFHQNX1H7L + PLACED ( 12 22 ) N ;
- clk_leaf_0_0_buf BUFX1P4H7L + PLACED ( 80 80 ) N ;
END COMPONENTS
NETS 2 ;
- clk ( clk_leaf_0_0_buf A )
  + ROUTED MET2 ( 80 80 ) ( 120 * )
  ;
- clk_leaf ( clk_leaf_0_0_buf Y ) ( U1 CK )
  + ROUTED MET3 ( 80 80 ) ( * 120 )
  ;
END NETS
END DESIGN
""".strip()
        + "\n",
    )

    FoundationExtractor(ws, profile="iccd_full_v1").extract(stages=["place", "CTS", "route"])

    foundation_dir = ws / "foundation_data" / "ecc"
    place_pin = json.loads((foundation_dir / "vectors" / "pins" / "place.jsonl").read_text(encoding="utf-8").splitlines()[0])
    cts_rows = [json.loads(line) for line in (foundation_dir / "vectors" / "pins" / "CTS.jsonl").read_text(encoding="utf-8").splitlines()]
    route_rows = [json.loads(line) for line in (foundation_dir / "vectors" / "pins" / "route.jsonl").read_text(encoding="utf-8").splitlines()]
    new_cts_pin = next(row for row in cts_rows if row["pin_key"] == "clk_leaf_0_0_buf:A")
    moved_cts_pin = next(row for row in cts_rows if row["pin_key"] == "U1:CK")
    route_pin = next(row for row in route_rows if row["pin_key"] == "clk_leaf_0_0_buf:A")

    assert place_pin["route_context"] is None
    assert place_pin["progressive_metadata"]["route_only_oracle"] is False
    assert "local_final_overflow" not in json.dumps(place_pin)
    assert new_cts_pin["progressive_metadata"]["available_from"] == "CTS"
    assert new_cts_pin["progressive_metadata"]["introduced_by_cts"] is True
    assert new_cts_pin["progressive_metadata"]["exists_in_place"] is False
    assert moved_cts_pin["progressive_metadata"]["prev_net"] == "clk"
    assert moved_cts_pin["progressive_metadata"]["net_changed_from_prev_stage"] is True
    assert moved_cts_pin["progressive_metadata"]["moved_from_prev_stage"] is True
    assert route_pin["route_context"]["route_only_oracle"] is True
    assert route_pin["progressive_metadata"]["route_only_oracle"] is True
    assert route_pin["route_context"]["net_routed_length"] == 40.0


def test_iccd_full_v1_writes_nested_net_wire_graph_patch_and_tech_records(tmp_path: Path):
    ws = _make_workspace(tmp_path)

    FoundationExtractor(ws, profile="iccd_full_v1").extract()

    foundation_dir = ws / "foundation_data" / "ecc"
    nets = [json.loads(line) for line in (foundation_dir / "vectors" / "nets" / "route.jsonl").read_text().splitlines()]
    n1 = next(row for row in nets if row["net_key"] == "n1")
    assert list(n1) == [
        "id",
        "stage",
        "net_key",
        "name",
        "source",
        "identity",
        "connectivity_summary",
        "terminal_refs",
        "geometry_proxy",
        "patch_anchor",
        "timing_context",
        "route_analysis",
        "progressive_metadata",
        "source_refs",
        "null_reason",
    ]
    assert n1["identity"]["net_class"] == "signal"
    assert n1["connectivity_summary"]["terminal_count"] >= 2
    assert n1["connectivity_summary"]["pin_count"] == n1["connectivity_summary"]["terminal_count"]
    assert n1["terminal_refs"]
    terminal_ref = n1["terminal_refs"][0]
    assert {
        "pin_key",
        "pin_kind",
        "instance",
        "parent_instance_key",
        "parent_master",
        "pin_name",
        "full_name",
        "pin_role",
        "is_driver",
        "is_sink",
        "is_io",
        "is_macro_pin",
        "patch_id",
        "geometry_status",
        "anchor_source",
        "is_on_critical_path",
    } <= set(terminal_ref)
    assert n1["geometry_proxy"]["hpwl"] is not None
    assert {
        "anchor_source",
        "anchor_quality",
        "terminal_bbox",
        "terminal_center",
        "hpwl",
        "x_span",
        "y_span",
        "area",
        "aspect_ratio",
        "patch_ids",
        "patch_span_count",
        "cross_patch",
        "exact_terminal_count",
        "fallback_terminal_count",
        "missing_anchor_terminal_count",
    } <= set(n1["geometry_proxy"])
    assert n1["geometry_proxy"]["cross_patch"] == (n1["geometry_proxy"]["patch_span_count"] > 1)
    assert n1["geometry_proxy"]["anchor_quality"] in {
        "all_exact",
        "mixed_exact_and_fallback",
        "all_fallback",
        "missing",
    }
    assert {
        "primary_patch_id",
        "patch_ids",
        "patch_span_count",
        "anchor_source",
        "local_cell_density_mean",
        "local_pin_density_mean",
        "local_rudy_mean",
        "local_rudy_max",
        "local_egr_overflow_mean",
        "local_egr_overflow_max",
        "terminal_count_by_patch",
    } <= set(n1["patch_anchor"])
    assert {
        "available",
        "timing_path_count",
        "is_on_critical_path",
        "worst_slack_seen",
        "min_arrival",
        "max_arrival",
        "max_slew",
        "max_cap",
        "driver_pin_keys",
        "endpoint_pin_count",
        "path_refs",
        "source",
    } <= set(n1["timing_context"])
    assert n1["route_analysis"]["route_only_oracle"] is True
    assert {
        "route_only_oracle",
        "routed_wire_count",
        "routed_wire_length",
        "routed_bbox",
        "covered_layers",
        "via_count",
        "detour_ratio",
        "routed_patch_ids",
        "routed_patch_count",
        "overlapped_congested_patch_count",
        "final_overflow_sum",
        "final_overflow_max",
        "patch_attribution_refs",
        "source",
    } <= set(n1["route_analysis"])
    assert n1["route_analysis"]["routed_wire_length"] > 0
    assert n1["route_analysis"]["routed_wire_count"] > 0
    assert n1["route_analysis"]["routed_patch_count"] == len(n1["route_analysis"]["routed_patch_ids"])
    assert n1["route_analysis"]["detour_ratio"] == n1["route_analysis"]["routed_wire_length"] / n1["geometry_proxy"]["hpwl"]
    assert n1["route_analysis"]["final_overflow_sum"] == 8.0
    assert n1["route_analysis"]["final_overflow_max"] == 5.0
    assert {
        "patch_id",
        "wire_length_in_patch",
        "via_count_in_patch",
        "final_overflow",
        "wire_segment_count",
        "covered_layers",
        "contribution_score",
    } <= set(n1["route_analysis"]["patch_attribution_refs"][0])
    assert n1["route_analysis"]["via_count"] >= 0
    assert {
        "available_from",
        "created_stage",
        "created_stage_source",
        "exists_in_prev_stage",
        "exists_in_place",
        "introduced_by_cts",
        "prev_net_key",
        "renamed_from_prev_stage",
        "terminal_count_changed_from_prev_stage",
        "hpwl_delta_from_prev_stage",
        "patch_span_delta_from_prev_stage",
        "route_only_oracle",
    } <= set(n1["progressive_metadata"])
    assert n1["progressive_metadata"]["exists_in_prev_stage"] is True
    assert n1["progressive_metadata"]["exists_in_place"] is True
    assert n1["source_refs"]["def"] == "route_ecc/output/gcd_route.def"
    assert n1["source_refs"]["def_section"] == "NETS"
    assert n1["source_refs"]["def_index"] == 0
    assert n1["source_refs"]["sta"] == "route_ecc/data/sta/gcd.rpt.json"
    assert n1["source_refs"]["route"] == "route_ecc/output/gcd_route.def"

    place_nets = [json.loads(line) for line in (foundation_dir / "vectors" / "nets" / "place.jsonl").read_text().splitlines()]
    place_n1 = next(row for row in place_nets if row["net_key"] == "n1")
    assert place_n1["route_analysis"] is None
    assert place_n1["null_reason"]["route_analysis"] == "route_only_not_available_for_preroute_stage"
    assert place_n1["progressive_metadata"]["route_only_oracle"] is False
    assert "final_overflow" not in json.dumps(place_n1["patch_anchor"])

    wires = [json.loads(line) for line in (foundation_dir / "vectors" / "wires" / "route.jsonl").read_text().splitlines()]
    wire = next(row for row in wires if row["identity"]["net_key"] == "n1" and row["identity"]["segment_kind"] == "wire_segment")
    assert list(wire) == [
        "id",
        "stage",
        "wire_key",
        "source",
        "identity",
        "geometry",
        "layer_context",
        "track_context",
        "capacity_context",
        "patch_anchor",
        "patch_intersections",
        "net_context",
        "endpoint_context",
        "timing_context",
        "route_context",
        "via_context",
        "progressive_metadata",
        "source_refs",
        "null_reason",
        "net",
        "layer",
        "direction",
        "x1",
        "y1",
        "x2",
        "y2",
        "length",
        "width",
        "via",
        "special",
    ]
    assert wire["wire_key"].startswith("route:NETS:n1:")
    assert wire["geometry"]["segment_kind"] == "wire_segment"
    assert wire["geometry"]["bbox"] is not None
    assert wire["patch_intersections"]
    assert wire["net_context"]["terminal_count"] >= 2
    assert wire["route_context"]["route_only_oracle"] is True
    assert any(row["identity"]["segment_kind"] == "wire_segment" for row in wires)

    pre_route_graphs = (foundation_dir / "vectors" / "routing_graphs" / "place.jsonl").read_text(encoding="utf-8")
    assert pre_route_graphs == ""
    route_graphs = [json.loads(line) for line in (foundation_dir / "vectors" / "routing_graphs" / "route.jsonl").read_text().splitlines()]
    graph = next(row for row in route_graphs if row["net_key"] == "n1")
    assert list(graph) == [
        "id",
        "stage",
        "graph_key",
        "net_key",
        "name",
        "source",
        "identity",
        "graph_semantics",
        "vertices",
        "edges",
        "patch_footprint",
        "graph_metrics",
        "terminal_matching",
        "timing_context",
        "route_context",
        "progressive_metadata",
        "source_refs",
        "coverage",
        "null_reason",
    ]
    assert graph["identity"]["has_routed_geometry"] is True
    assert graph["graph_semantics"]["topology_direction"] == "undirected"
    assert graph["graph_metrics"]["wire_edge_count"] > 0
    assert graph["graph_metrics"]["via_edge_count"] == 1
    assert graph["graph_metrics"]["total_routed_length"] == 800.0
    assert graph["graph_metrics"]["used_layers"] == ["MET2", "MET3"]
    assert graph["graph_metrics"]["layer_count"] == 2
    assert graph["graph_metrics"]["max_vertex_degree"] >= 1
    assert graph["graph_metrics"]["terminal_vertex_count"] >= 1
    assert graph["patch_footprint"]["touched_patch_count"] >= 1
    assert graph["patch_footprint"]["touched_patch_ids"]
    assert graph["patch_footprint"]["dominant_patch_id"] in graph["patch_footprint"]["touched_patch_ids"]
    assert graph["patch_footprint"]["total_routed_length_by_patch"]
    assert graph["patch_footprint"]["layer_usage_by_patch"]
    assert graph["patch_footprint"]["touched_layer_ids"] == ["MET2", "MET3"]
    assert isinstance(graph["patch_footprint"]["cross_patch"], bool)
    assert graph["terminal_matching"]["strategy"] == "exact_shape_then_nearest_same_net"
    assert graph["terminal_matching"]["expected_terminal_count"] >= 2
    assert graph["terminal_matching"]["matched_terminal_count"] >= 1
    assert graph["terminal_matching"]["terminal_match_rate"] is not None
    assert graph["route_context"]["route_only_oracle"] is True
    assert graph["route_context"]["source"] == "route_ecc/output/gcd_route.def"
    assert graph["route_context"]["total_routed_length"] == 800.0
    assert graph["route_context"]["via_count"] == 1
    assert graph["route_context"]["wire_segment_count"] == 4
    assert graph["progressive_metadata"] == {
        "available_from": "route",
        "created_stage": "route",
        "exists_before_route": False,
        "not_available_before_route": True,
        "route_only_oracle": True,
        "pre_route_placeholder_policy": "empty_stage_file",
    }
    assert graph["coverage"]["has_routed_geometry"] is True
    assert graph["coverage"]["wire_ref_count"] == graph["graph_metrics"]["wire_edge_count"]
    assert graph["coverage"]["via_ref_count"] == graph["graph_metrics"]["via_edge_count"]
    assert graph["coverage"]["terminal_match_rate"] == graph["terminal_matching"]["terminal_match_rate"]
    assert graph["coverage"]["edge_patch_intersection_coverage"] == 1.0
    assert graph["coverage"]["connected_component_count"] == graph["graph_metrics"]["connected_component_count"]
    assert "patch_intersection_count" not in graph["coverage"]
    assert "patch_count" not in graph["patch_footprint"]

    via_edge = next(edge for edge in graph["edges"] if edge["edge_kind"] == "via_transition")
    assert via_edge["edge_key"] == f"{graph['graph_key']}:e{via_edge['edge_id']}"
    assert via_edge["source_vertex_id"] != via_edge["target_vertex_id"]
    assert via_edge["geometry"]["start"]["layer"] == "MET2"
    assert via_edge["geometry"]["end"]["layer"] == "MET3"
    assert via_edge["geometry"]["direction"] == "point"
    assert via_edge["via_ref"] == {
        "via_name": "VIA23",
        "coordinate": {"x": 60.0, "y": 60.0},
        "from_layer": "MET2",
        "to_layer": "MET3",
    }
    assert via_edge["patch_intersections"][0]["layer"] == "MET2/MET3"
    assert via_edge["patch_intersections"][0]["intersection_kind"] == "via_point"
    assert via_edge["source_refs"]["def"] == "route_ecc/output/gcd_route.def"
    assert via_edge["null_reason"].get("wire_ref") == "via_transition_has_no_wire_segment_ref"

    wire_edge = next(edge for edge in graph["edges"] if edge["edge_kind"] == "wire_segment")
    assert wire_edge["source_vertex_id"] != wire_edge["target_vertex_id"]
    assert wire_edge["wire_ref"]["wire_key"].startswith("route:NETS:n1:")
    assert wire_edge["via_ref"] is None
    assert wire_edge["patch_intersections"][0]["layer"] == wire_edge["geometry"]["layer"]
    assert wire_edge["patch_intersections"][0]["intersection_kind"] == "segment_overlap"

    assert all("terminal_match" in vertex for vertex in graph["vertices"])
    assert all("source_refs" in vertex for vertex in graph["vertices"])
    assert all("null_reason" in vertex for vertex in graph["vertices"])
    assert all(len(vertex["incident_edge_ids"]) == len(set(vertex["incident_edge_ids"])) for vertex in graph["vertices"])
    assert any(vertex["vertex_kind"] == "terminal_anchor" for vertex in graph["vertices"])
    assert any(vertex["vertex_kind"] == "via_point" for vertex in graph["vertices"])

    patches = [json.loads(line) for line in (foundation_dir / "vectors" / "patches" / "route.jsonl").read_text().splitlines()]
    patch = patches[0]
    assert list(patch)[:19] == [
        "id",
        "stage",
        "patch_key",
        "source",
        "identity",
        "geometry",
        "local_density",
        "local_connectivity",
        "pre_route_estimators",
        "neighbor_context",
        "entity_refs",
        "timing_context",
        "electrical_context",
        "route_oracle",
        "label_refs",
        "drc_context",
        "progressive_metadata",
        "source_refs",
        "null_reason",
    ]
    assert patch["patch_key"] == "patch:0"
    assert patch["identity"]["grid_patch_count"] == 4
    assert patch["local_density"]["available_for_training_input"] is False
    assert patch["local_connectivity"]["available_for_training_input"] is False
    assert patch["pre_route_estimators"]["available_for_training_input"] is False
    assert patch["neighbor_context"]["available_for_training_input"] is False
    assert patch["neighbor_context"]["window_3x3_patch_ids"]
    assert patch["entity_refs"]["wire_count"] >= 1
    assert patch["route_oracle"]["route_only_oracle"] is True
    assert patch["label_refs"]["route_native_demand_capacity"] == "labels/route_native_demand_capacity.jsonl#patch_id=0"

    layers = json.loads((foundation_dir / "vectors" / "tech" / "layers.json").read_text(encoding="utf-8"))
    cells = json.loads((foundation_dir / "vectors" / "tech" / "cells.json").read_text(encoding="utf-8"))
    vias = json.loads((foundation_dir / "vectors" / "tech" / "vias.json").read_text(encoding="utf-8"))
    tech_summary = json.loads((foundation_dir / "vectors" / "tech" / "tech_summary.json").read_text(encoding="utf-8"))
    assert layers[0]["identity"]["name"] == layers[0]["name"]
    assert "routing_properties" in layers[0]
    assert cells[0]["identity"]["name"] == cells[0]["name"]
    assert cells[0]["usage_summary"]["instance_count"] >= 1
    assert vias[0]["identity"]["name"] == vias[0]["name"]
    assert "layer_stack" in vias[0]
    assert tech_summary["counts"] == {
        "layer_count": len(layers),
        "cell_count": len(cells),
        "via_count": len(vias),
        "stage_count": 5,
    }


def test_routing_graph_records_follow_vec_routing_graph_schema(tmp_path: Path):
    ws = _make_workspace(tmp_path)

    FoundationExtractor(ws, profile="iccd_full_v1").extract(stages=["place", "route"])

    foundation_dir = ws / "foundation_data" / "ecc"
    assert (foundation_dir / "vectors" / "routing_graphs" / "place.jsonl").read_text(encoding="utf-8") == ""
    route_graphs = [
        json.loads(line)
        for line in (foundation_dir / "vectors" / "routing_graphs" / "route.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    graph = next(row for row in route_graphs if row["net_key"] == "n1")

    required_patch_fields = {
        "primary_patch_id",
        "dominant_patch_id",
        "touched_patch_ids",
        "touched_patch_count",
        "total_routed_length_by_patch",
        "layer_usage_by_patch",
        "touched_layer_ids",
        "cross_patch",
    }
    assert required_patch_fields.issubset(graph["patch_footprint"])
    assert "patch_count" not in graph["patch_footprint"]
    assert "length_by_patch" not in graph["patch_footprint"]

    required_metric_fields = {
        "vertex_count",
        "edge_count",
        "wire_edge_count",
        "via_edge_count",
        "branch_vertex_count",
        "terminal_vertex_count",
        "connected_component_count",
        "total_routed_length",
        "layer_count",
        "used_layers",
        "max_vertex_degree",
        "has_cycle",
    }
    assert required_metric_fields.issubset(graph["graph_metrics"])
    assert graph["graph_metrics"]["total_routed_length"] == 800.0
    assert graph["graph_metrics"]["via_edge_count"] == 1

    assert graph["terminal_matching"]["strategy"] == "exact_shape_then_nearest_same_net"
    assert graph["terminal_matching"]["expected_terminal_count"] >= 2
    assert graph["terminal_matching"]["terminal_match_rate"] is not None
    assert graph["progressive_metadata"]["available_from"] == "route"
    assert graph["progressive_metadata"]["not_available_before_route"] is True
    assert graph["route_context"]["source"] == "route_ecc/output/gcd_route.def"
    assert graph["coverage"]["edge_patch_intersection_coverage"] == 1.0

    assert all({"terminal_match", "source_refs", "null_reason"}.issubset(vertex) for vertex in graph["vertices"])
    assert all({"edge_key", "source_vertex_id", "target_vertex_id", "wire_ref", "via_ref", "source_refs", "null_reason"}.issubset(edge) for edge in graph["edges"])
    assert all(
        {"layer", "intersection_kind"}.issubset(item)
        for edge in graph["edges"]
        for item in edge["patch_intersections"]
    )

    via_edge = next(edge for edge in graph["edges"] if edge["edge_kind"] == "via_transition")
    assert via_edge["source_vertex_id"] != via_edge["target_vertex_id"]
    assert via_edge["geometry"]["start"]["layer"] == "MET2"
    assert via_edge["geometry"]["end"]["layer"] == "MET3"
    assert via_edge["via_ref"]["from_layer"] == "MET2"
    assert via_edge["via_ref"]["to_layer"] == "MET3"
    assert all(len(vertex["incident_edge_ids"]) == len(set(vertex["incident_edge_ids"])) for vertex in graph["vertices"])
