#!/usr/bin/env python
# -*- encoding: utf-8 -*-

import json
from types import SimpleNamespace

from chipcompiler.data import Workspace, WorkspaceStep
from chipcompiler.tools.ecc.runner import save_data


class FakeEccModule:
    def __init__(self):
        self.calls = []

    def def_save(self, **kwargs):
        self.calls.append(("def_save", kwargs))

    def verilog_save(self, **kwargs):
        self.calls.append(("verilog_save", kwargs))

    def gds_save(self, **kwargs):
        self.calls.append(("gds_save", kwargs))

    def json_save(self, **kwargs):
        self.calls.append(("json_save", kwargs))

    def feature_sammry(self, **kwargs):
        self.calls.append(("feature_sammry", kwargs))

    def feature_step(self, **kwargs):
        self.calls.append(("feature_step", kwargs))

    def report_summary(self, **kwargs):
        self.calls.append(("report_summary", kwargs))

    def init_sta(self, **kwargs):
        self.calls.append(("init_sta", kwargs))

    def build_timing_rc_tree(self, *args, **kwargs):
        self.calls.append(("build_timing_rc_tree", args, kwargs))

    def report_timing(self, *args, **kwargs):
        self.calls.append(("report_timing", args, kwargs))


def test_save_data_builds_stage_rc_tree_before_reporting_timing(tmp_path):
    workspace = Workspace()
    workspace.design = SimpleNamespace(top_module="gcd")
    workspace.pdk = SimpleNamespace(libs=["lib.lib"], sdc="gcd.sdc")

    step = WorkspaceStep(
        name="route_ecc",
        output={"def": str(tmp_path / "route.def"), "json": str(tmp_path / "route.json")},
        data={"sta": str(tmp_path / "sta")},
        feature={"summary": str(tmp_path / "summary.json"), "step": str(tmp_path / "step.json"), "db": str(tmp_path / "missing_db.json")},
        report={"db": str(tmp_path / "db.rpt")},
    )
    module = FakeEccModule()

    assert save_data(workspace, step, module)

    call_names = [call[0] for call in module.calls]
    assert "build_timing_rc_tree" in call_names
    assert call_names.index("init_sta") < call_names.index("build_timing_rc_tree")
    assert call_names.index("build_timing_rc_tree") < call_names.index("report_timing")
    build_call = module.calls[call_names.index("build_timing_rc_tree")]
    assert build_call[2] == {"routing_type": "ROUTED"}


def test_build_step_config_writes_space_router_stop_flag_from_parameters(tmp_path):
    from chipcompiler.tools.ecc.builder import build_step_config

    workspace = Workspace(directory=str(tmp_path / "ws"))
    workspace.design = SimpleNamespace(name="gcd")
    workspace.pdk = SimpleNamespace(
        tech="tech.lef",
        lefs=[],
        libs=[],
        sdc="gcd.sdc",
        spef="",
        buffers=[],
        fillers=[],
        mapping_file="",
        corners=[],
    )
    workspace.parameters = SimpleNamespace(
        path=str(tmp_path / "parameters.json"),
        data={
            "Bottom layer": "MET2",
            "Top layer": "MET5",
            "route_completion_mode": "space_router_label",
        },
    )
    (tmp_path / "parameters.json").write_text(
        '{"Bottom layer":"MET2","Top layer":"MET5","route_completion_mode":"space_router_label"}',
        encoding="utf-8",
    )
    step = WorkspaceStep(
        name="route",
        directory=str(tmp_path / "ws" / "route_ecc"),
        config={
            "dir": str(tmp_path / "ws" / "route_ecc" / "config"),
            "flow": str(tmp_path / "ws" / "route_ecc" / "config" / "flow_config.json"),
            "db": str(tmp_path / "ws" / "route_ecc" / "config" / "db_default_config.json"),
            "Floorplan": str(tmp_path / "ws" / "route_ecc" / "config" / "fp_default_config.json"),
            "place": str(tmp_path / "ws" / "route_ecc" / "config" / "pl_default_config.json"),
            "route": str(tmp_path / "ws" / "route_ecc" / "config" / "rt_default_config.json"),
            "drc": str(tmp_path / "ws" / "route_ecc" / "config" / "drc_default_config.json"),
            "CTS": str(tmp_path / "ws" / "route_ecc" / "config" / "cts_default_config.json"),
            "optDrv": str(tmp_path / "ws" / "route_ecc" / "config" / "to_default_config_drv.json"),
            "optHold": str(tmp_path / "ws" / "route_ecc" / "config" / "to_default_config_hold.json"),
            "optSetup": str(tmp_path / "ws" / "route_ecc" / "config" / "to_default_config_setup.json"),
            "PNP": str(tmp_path / "ws" / "route_ecc" / "config" / "pnp_default_config.json"),
            "RCX": str(tmp_path / "ws" / "route_ecc" / "config" / "rcx.json"),
            "fixFanout": str(tmp_path / "ws" / "route_ecc" / "config" / "no_default_config_fixfanout.json"),
        },
        input={"def": "in.def", "verilog": "in.v"},
        output={"dir": str(tmp_path / "ws" / "route_ecc" / "output")},
        data={"route": str(tmp_path / "ws" / "route_ecc" / "data" / "rt")},
    )
    build_step_config(workspace, step)

    rt_config_path = tmp_path / "ws" / "route_ecc" / "config" / "rt_default_config.json"
    rt_config = json.loads(rt_config_path.read_text(encoding="utf-8"))
    assert rt_config["RT"]["-stop_after_stage"] == "space_router"

    (tmp_path / "parameters.json").write_text(
        '{"Bottom layer":"MET2","Top layer":"MET5","route_completion_mode":"full_route"}',
        encoding="utf-8",
    )

    build_step_config(workspace, step)

    rt_config = json.loads(rt_config_path.read_text(encoding="utf-8"))
    assert "-stop_after_stage" not in rt_config["RT"]


def test_engine_flow_accepts_space_router_label_artifact_as_route_success(tmp_path):
    from chipcompiler.engine.flow import EngineFlow

    workspace = Workspace(directory=str(tmp_path / "ws"))
    workspace.parameters = SimpleNamespace(data={"route_completion_mode": "space_router_label"})
    step = WorkspaceStep(
        name="route",
        output={
            "def": str(tmp_path / "ws" / "route_ecc" / "output" / "gcd_route.def.gz"),
            "verilog": str(tmp_path / "ws" / "route_ecc" / "output" / "gcd_route.v"),
            "gds": str(tmp_path / "ws" / "route_ecc" / "output" / "gcd_route.gds"),
        },
        data={"route": str(tmp_path / "ws" / "route_ecc" / "data" / "rt")},
    )
    label_path = tmp_path / "ws" / "route_ecc" / "data" / "rt" / "space_router" / "route_native_demand_capacity_final.jsonl"
    label_path.parent.mkdir(parents=True)
    label_path.write_text('{"patch_id":0}\n', encoding="utf-8")

    assert EngineFlow(workspace).check_step_result(step)


def test_tool_run_step_recreates_step_space_before_config(monkeypatch, tmp_path):
    import chipcompiler.tools.eda as eda

    calls = []

    class FakeModule:
        @staticmethod
        def is_eda_exist():
            return True

        @staticmethod
        def build_step_space(step):
            calls.append("build_step_space")
            (tmp_path / "route_ecc" / "data" / "rt").mkdir(parents=True)

        @staticmethod
        def build_step_config(workspace, step):
            calls.append("build_step_config")
            assert (tmp_path / "route_ecc" / "data" / "rt").is_dir()

        @staticmethod
        def run_step(workspace, step, ecc_module=None):
            calls.append("run_step")
            return True

    monkeypatch.setattr(eda, "load_eda_module", lambda tool: FakeModule)
    workspace = Workspace(directory=str(tmp_path))
    step = WorkspaceStep(name="route", tool="ecc", directory=str(tmp_path / "route_ecc"))

    assert eda.run_step(workspace, step)
    assert calls == ["build_step_space", "build_step_config", "run_step"]
