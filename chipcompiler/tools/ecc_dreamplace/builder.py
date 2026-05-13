#!/usr/bin/env python

from __future__ import annotations

import shutil
from copy import deepcopy
from pathlib import Path

from chipcompiler.data import Workspace, WorkspaceStep
from chipcompiler.tools.ecc import builder as ecc_builder
from chipcompiler.utility import json_read, json_write


_ECOS_TO_DREAMPLACE_PARAMETERS = {
    "Target density": "target_density",
    "Target overflow": "stop_overflow",
    "Cell padding x": "cell_padding_x",
    "Routability opt flag": "routability_opt_flag",
}


def apply_parameter_overrides(
    base_params: dict,
    parameter_data: dict,
) -> dict:
    """Apply ECOS and direct DreamPlace overrides to a DreamPlace config.

    Top-level ECOS parameters provide the normal GUI/API surface. The nested
    ``DreamPlace`` mapping remains available for advanced direct overrides and
    intentionally takes precedence when both surfaces set the same field.
    """
    params = deepcopy(base_params)

    for ecos_key, dreamplace_key in _ECOS_TO_DREAMPLACE_PARAMETERS.items():
        if ecos_key in parameter_data:
            params[dreamplace_key] = deepcopy(parameter_data[ecos_key])

    dreamplace_overrides = parameter_data.get("DreamPlace", {})
    if not isinstance(dreamplace_overrides, dict):
        return params

    for key, value in dreamplace_overrides.items():
        params[key] = deepcopy(value)

    return params


def build_step(
    workspace: Workspace,
    step_name: str,
    input_def: str,
    input_verilog: str,
    input_db: str | None = None,
    output_def: str | None = None,
    output_verilog: str | None = None,
    output_gds: str | None = None,
) -> WorkspaceStep:
    step = ecc_builder.build_step(
        workspace=workspace,
        step_name=step_name,
        input_def=input_def,
        input_verilog=input_verilog,
        input_db=input_db,
        output_def=output_def,
        output_verilog=output_verilog,
        output_gds=output_gds,
        tool="dreamplace",
    )

    step.config["dreamplace"] = f"{step.config['dir']}/dreamplace.json"

    return step


def build_step_space(step: WorkspaceStep) -> None:
    ecc_builder.build_step_space(step)


def build_step_config(workspace: Workspace, step: WorkspaceStep) -> None:
    # build ecc config
    ecc_builder.build_step_config(workspace, step)

    # build workspace/place_dreamplace/config/dreamplace.json

    # resolve the absolute path to configs/dreamplace.json relative to this script,
    # then copy it to the destination specified by step.config["dreamplace"]
    param_src = Path(__file__).resolve().parent / "configs" / "dreamplace.json"
    shutil.copy2(param_src, step.config["dreamplace"])

    params = json_read(step.config["dreamplace"])

    params["lef_input"] = [workspace.pdk.tech, *workspace.pdk.lefs]
    params["def_input"] = step.input.get("def", "")
    params["verilog_input"] = step.input.get("verilog", "")
    params["result_dir"] = step.data.get(step.name, step.data["dir"])
    params["base_design_name"] = workspace.design.name
    params = apply_parameter_overrides(params, workspace.parameters.data)

    json_write(step.config["dreamplace"], params)
