"""Lazy public exports for ECC tool integration."""

from __future__ import annotations

_EXPORTS = {
    "builder": ("chipcompiler.tools.ecc.builder", None),
    "runner": ("chipcompiler.tools.ecc.runner", None),
    "build_step": ("chipcompiler.tools.ecc.builder", "build_step"),
    "build_step_space": ("chipcompiler.tools.ecc.builder", "build_step_space"),
    "build_step_config": ("chipcompiler.tools.ecc.builder", "build_step_config"),
    "create_db_engine": ("chipcompiler.tools.ecc.runner", "create_db_engine"),
    "run_step": ("chipcompiler.tools.ecc.runner", "run_step"),
    "ECCToolsModule": ("chipcompiler.tools.ecc.module", "ECCToolsModule"),
    "ECCToolsPlot": ("chipcompiler.tools.ecc.plot", "ECCToolsPlot"),
    "build_step_metrics": ("chipcompiler.tools.ecc.metrics", "build_step_metrics"),
    "get_step_info": ("chipcompiler.tools.ecc.service", "get_step_info"),
    "EccSubFlow": ("chipcompiler.tools.ecc.subflow", "EccSubFlow"),
    "EccSubFlowEnum": ("chipcompiler.tools.ecc.subflow", "EccSubFlowEnum"),
    "EccChecklist": ("chipcompiler.tools.ecc.checklist", "EccChecklist"),
    "is_eda_exist": ("chipcompiler.tools.ecc.utility", "is_eda_exist"),
}

__all__ = [name for name in _EXPORTS if name not in {"builder", "runner"}]


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = _EXPORTS[name]
    from importlib import import_module

    module = import_module(module_name)
    value = module if attr_name is None else getattr(module, attr_name)
    globals()[name] = value
    return value
