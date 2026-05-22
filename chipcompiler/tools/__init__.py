"""Lazy public exports for EDA tool helpers.

Keep this package lightweight: importing a specific submodule such as
``chipcompiler.tools.ecc.module`` must not eagerly import plotting or engine
helpers, because ecc-tools' native extension can abort when combined with those
heavy imports in the wrong order.
"""

from __future__ import annotations

_EXPORTS = {
    "load_eda_module": ("chipcompiler.tools.eda", "load_eda_module"),
    "create_step": ("chipcompiler.tools.eda", "create_step"),
    "run_step": ("chipcompiler.tools.eda", "run_step"),
    "save_layout_image": ("chipcompiler.tools.eda", "save_layout_image"),
    "build_step_metrics": ("chipcompiler.tools.eda", "build_step_metrics"),
    "get_step_info": ("chipcompiler.tools.eda", "get_step_info"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = _EXPORTS[name]
    from importlib import import_module

    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value
