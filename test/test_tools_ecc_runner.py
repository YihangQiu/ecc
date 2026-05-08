#!/usr/bin/env python
# -*- encoding: utf-8 -*-

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
