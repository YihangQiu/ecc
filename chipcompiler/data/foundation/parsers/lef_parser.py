from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LefPin:
    name: str
    direction: str | None = None
    use: str | None = None
    shapes: list[dict[str, Any]] = field(default_factory=list)
    source: str | None = None


@dataclass(frozen=True)
class LefMacro:
    name: str
    pins: dict[str, LefPin] = field(default_factory=dict)
    source: str | None = None
    size: dict[str, float] | None = None


_MACRO_RE = re.compile(r"^\s*MACRO\s+(\S+)")
_PIN_RE = re.compile(r"^\s*PIN\s+(\S+)")
_END_RE = re.compile(r"^\s*END(?:\s+(\S+))?\s*$")
_DIRECTION_RE = re.compile(r"\bDIRECTION\s+(\S+)\s*;")
_USE_RE = re.compile(r"\bUSE\s+(\S+)\s*;")
_LAYER_RE = re.compile(r"\bLAYER\s+(\S+)\s*;")
_RECT_RE = re.compile(r"\bRECT\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*;")
_SIZE_RE = re.compile(r"\bSIZE\s+(-?\d+(?:\.\d+)?)\s+BY\s+(-?\d+(?:\.\d+)?)\s*;")


def parse_lef(path: Path) -> dict[str, LefMacro]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    macros: dict[str, LefMacro] = {}
    macro_name: str | None = None
    macro_pins: dict[str, LefPin] = {}
    macro_size: dict[str, float] | None = None
    pin_name: str | None = None
    pin_direction: str | None = None
    pin_use: str | None = None
    pin_shapes: list[dict[str, Any]] = []
    current_layer: str | None = None
    port_index = -1

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if macro_name is None:
            macro_match = _MACRO_RE.match(stripped)
            if macro_match:
                macro_name = macro_match.group(1)
                macro_pins = {}
                macro_size = None
            continue
        if pin_name is None:
            size_match = _SIZE_RE.search(stripped)
            if size_match:
                macro_size = {"width": float(size_match.group(1)), "height": float(size_match.group(2))}
            pin_match = _PIN_RE.match(stripped)
            if pin_match:
                pin_name = pin_match.group(1)
                pin_direction = None
                pin_use = None
                pin_shapes = []
                current_layer = None
                port_index = -1
                continue
            end_match = _END_RE.match(stripped)
            if end_match and end_match.group(1) == macro_name:
                macros[macro_name] = LefMacro(name=macro_name, pins=macro_pins, source=str(path), size=macro_size)
                macro_name = None
                macro_pins = {}
            continue

        direction_match = _DIRECTION_RE.search(stripped)
        if direction_match:
            pin_direction = direction_match.group(1).upper()
        use_match = _USE_RE.search(stripped)
        if use_match:
            pin_use = use_match.group(1).upper()
        if stripped == "PORT":
            port_index += 1
            current_layer = None
        layer_match = _LAYER_RE.search(stripped)
        if layer_match:
            current_layer = layer_match.group(1)
        rect_match = _RECT_RE.search(stripped)
        if rect_match and current_layer:
            llx, lly, urx, ury = (float(rect_match.group(i)) for i in range(1, 5))
            pin_shapes.append(
                {
                    "shape_id": len(pin_shapes),
                    "port_index": max(port_index, 0),
                    "layer": current_layer,
                    "shape_type": "rect",
                    "rect": {"llx": llx, "lly": lly, "urx": urx, "ury": ury},
                    "polygon": None,
                    "source": "lef_pin_rect",
                }
            )
        end_match = _END_RE.match(stripped)
        if end_match and end_match.group(1) == pin_name:
            macro_pins[pin_name] = LefPin(
                name=pin_name,
                direction=pin_direction,
                use=pin_use,
                shapes=pin_shapes,
                source=str(path),
            )
            pin_name = None
            current_layer = None
            port_index = -1
    return macros


def parse_lef_files(paths: list[Path]) -> dict[str, LefMacro]:
    macros: dict[str, LefMacro] = {}
    for path in paths:
        for name, macro in parse_lef(path).items():
            macros.setdefault(name, macro)
    return macros
