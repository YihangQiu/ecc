from __future__ import annotations

from chipcompiler.tools.ecc_dreamplace.builder import apply_parameter_overrides


def test_top_level_ecos_parameters_map_to_dreamplace_config():
    base = {
        "target_density": 0.8,
        "stop_overflow": 0.2,
        "cell_padding_x": 1,
        "routability_opt_flag": 0,
    }
    parameter_data = {
        "Target density": 0.55,
        "Target overflow": 0.12,
        "Cell padding x": 400,
        "Routability opt flag": 1,
    }

    updated = apply_parameter_overrides(base, parameter_data)

    assert updated["target_density"] == 0.55
    assert updated["stop_overflow"] == 0.12
    assert updated["cell_padding_x"] == 400
    assert updated["routability_opt_flag"] == 1
    assert base["target_density"] == 0.8


def test_direct_dreamplace_overrides_take_precedence_over_ecos_parameter_mapping():
    base = {"target_density": 0.8, "stop_overflow": 0.2}
    parameter_data = {
        "Target density": 0.55,
        "Target overflow": 0.12,
        "DreamPlace": {"target_density": 0.66},
    }

    updated = apply_parameter_overrides(base, parameter_data)

    assert updated["target_density"] == 0.66
    assert updated["stop_overflow"] == 0.12
