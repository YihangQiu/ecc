from __future__ import annotations

import gzip
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class DefTrack:
    axis: str
    start: float
    count: int
    step: float
    layer: str


@dataclass(frozen=True)
class DefRow:
    name: str
    site: str
    x: float
    y: float
    orient: str
    count_x: int
    count_y: int
    step_x: float
    step_y: float


@dataclass(frozen=True)
class DefWire:
    net: str
    layer: str
    x1: float
    y1: float
    x2: float
    y2: float
    width: float | None = None
    via: str | None = None
    special: bool = False

    @property
    def length(self) -> float:
        return abs(self.x2 - self.x1) + abs(self.y2 - self.y1)

    @property
    def direction(self) -> str:
        if abs(self.x2 - self.x1) >= abs(self.y2 - self.y1):
            return "horizontal"
        return "vertical"


@dataclass(frozen=True)
class DefNet:
    name: str
    pins: list[dict[str, Any]] = field(default_factory=list)
    wires: list[DefWire] = field(default_factory=list)
    special: bool = False


@dataclass(frozen=True)
class DefData:
    path: Path
    units: int | None
    diearea: dict[str, float] | None
    gcell_x: list[float]
    gcell_y: list[float]
    rows: list[DefRow]
    tracks: list[DefTrack]
    vias: list[dict[str, Any]]
    components: list[dict[str, Any]]
    pins: list[dict[str, Any]]
    nets: list[DefNet]


_COMPONENT_RE = re.compile(r"^\s*-\s+(\S+)\s+(\S+)(.*)")
_PLACED_RE = re.compile(r"\+\s+(?:PLACED|FIXED)\s+\(\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\)\s+(\S+)")
_PIN_RE = re.compile(r"\(\s+(\S+)\s+(\S+)\s+\)")
_POINT_RE = re.compile(r"\(\s*(-?\d+(?:\.\d+)?|\*)\s+(-?\d+(?:\.\d+)?|\*)\s+\)")


def parse_def(path: Path) -> DefData:
    text = _read_text(path)
    lines = [line.rstrip() for line in text.splitlines()]
    units = _parse_units(lines)
    diearea = _parse_diearea(lines)
    return DefData(
        path=path,
        units=units,
        diearea=diearea,
        gcell_x=_parse_gcell_axis(lines, "X"),
        gcell_y=_parse_gcell_axis(lines, "Y"),
        rows=_parse_rows(lines),
        tracks=_parse_tracks(lines),
        vias=_parse_vias(lines),
        components=_parse_components(lines),
        pins=_parse_pins(lines),
        nets=[*_parse_nets(lines, "NETS", special=False), *_parse_nets(lines, "SPECIALNETS", special=True)],
    )


def _read_text(path: Path) -> str:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    return path.read_text(encoding="utf-8", errors="replace")


def _parse_units(lines: list[str]) -> int | None:
    for line in lines:
        match = re.search(r"UNITS\s+DISTANCE\s+MICRONS\s+(\d+)", line)
        if match:
            return int(match.group(1))
    return None


def _parse_diearea(lines: list[str]) -> dict[str, float] | None:
    for line in lines:
        match = re.search(
            r"DIEAREA\s+\(\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\)\s+\(\s*(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*\)",
            line,
        )
        if match:
            llx, lly, urx, ury = (float(match.group(i)) for i in range(1, 5))
            return {"llx": llx, "lly": lly, "urx": urx, "ury": ury}
    return None


def _parse_gcell_axis(lines: list[str], axis: str) -> list[float]:
    values: list[float] = []
    for line in lines:
        match = re.search(rf"GCELLGRID\s+{axis}\s+(-?\d+(?:\.\d+)?)\s+DO\s+(\d+)\s+STEP\s+(-?\d+(?:\.\d+)?)", line)
        if not match:
            continue
        start = float(match.group(1))
        count = int(match.group(2))
        step = float(match.group(3))
        for idx in range(count):
            value = start + idx * step
            if not values or value > values[-1]:
                values.append(value)
    return values


def _parse_tracks(lines: list[str]) -> list[DefTrack]:
    tracks: list[DefTrack] = []
    for line in lines:
        match = re.search(r"TRACKS\s+([XY])\s+(-?\d+(?:\.\d+)?)\s+DO\s+(\d+)\s+STEP\s+(-?\d+(?:\.\d+)?)\s+LAYER\s+(\S+)", line)
        if match:
            tracks.append(
                DefTrack(
                    axis=match.group(1),
                    start=float(match.group(2)),
                    count=int(match.group(3)),
                    step=float(match.group(4)),
                    layer=match.group(5),
                )
            )
    return tracks


def _parse_rows(lines: list[str]) -> list[DefRow]:
    rows: list[DefRow] = []
    for line in lines:
        match = re.search(
            r"ROW\s+(\S+)\s+(\S+)\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+(\S+)\s+DO\s+(\d+)\s+BY\s+(\d+)\s+STEP\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)",
            line,
        )
        if match:
            rows.append(
                DefRow(
                    name=match.group(1),
                    site=match.group(2),
                    x=float(match.group(3)),
                    y=float(match.group(4)),
                    orient=match.group(5),
                    count_x=int(match.group(6)),
                    count_y=int(match.group(7)),
                    step_x=float(match.group(8)),
                    step_y=float(match.group(9)),
                )
            )
    return rows


def _parse_vias(lines: list[str]) -> list[dict[str, Any]]:
    vias: list[dict[str, Any]] = []
    in_vias = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("VIAS "):
            in_vias = True
            continue
        if in_vias and stripped.startswith("END VIAS"):
            break
        if in_vias and stripped.startswith("- "):
            tokens = stripped.split()
            layers = []
            if "+ LAYERS" in stripped:
                layers = stripped.split("+ LAYERS", 1)[1].replace(";", "").split()[:3]
            vias.append({"name": tokens[1], "layers": layers, "source": "def_vias"})
    return vias


def _parse_components(lines: list[str]) -> list[dict[str, Any]]:
    components: list[dict[str, Any]] = []
    in_components = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("COMPONENTS "):
            in_components = True
            continue
        if in_components and stripped.startswith("END COMPONENTS"):
            break
        if not in_components:
            continue
        match = _COMPONENT_RE.match(line)
        if not match:
            continue
        name, master, rest = match.groups()
        placed = _PLACED_RE.search(rest)
        components.append(
            {
                "name": name,
                "master": master,
                "origin": {"x": float(placed.group(1)), "y": float(placed.group(2))} if placed else None,
                "orientation": placed.group(3) if placed else None,
                "source": "def_components",
            }
        )
    return components


def _parse_pins(lines: list[str]) -> list[dict[str, Any]]:
    pins: list[dict[str, Any]] = []
    in_pins = False
    current: dict[str, Any] | None = None
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("PINS "):
            in_pins = True
            continue
        if in_pins and stripped.startswith("END PINS"):
            if current:
                pins.append(current)
            break
        if not in_pins:
            continue
        if stripped.startswith("- "):
            if current:
                pins.append(current)
            tokens = stripped.split()
            current = {"pin_name": tokens[1], "instance": "PIN", "source": "def_pins"}
        if current is None:
            continue
        net_match = re.search(r"\+\s+NET\s+(\S+)", stripped)
        if net_match:
            current["net"] = net_match.group(1)
        direction_match = re.search(r"\+\s+DIRECTION\s+(\S+)", stripped)
        if direction_match:
            current["direction"] = direction_match.group(1)
        placed = _PLACED_RE.search(stripped)
        if placed:
            current["origin"] = {"x": float(placed.group(1)), "y": float(placed.group(2))}
            current["orientation"] = placed.group(3)
    return pins


def _parse_nets(lines: list[str], section: str, *, special: bool) -> list[DefNet]:
    nets: list[DefNet] = []
    in_section = False
    current_name = ""
    current_chunks: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"{section} "):
            in_section = True
            continue
        if in_section and stripped.startswith(f"END {section}"):
            if current_name:
                nets.append(_net_from_chunks(current_name, current_chunks, special=special))
            break
        if not in_section:
            continue
        if stripped.startswith("- "):
            if current_name:
                nets.append(_net_from_chunks(current_name, current_chunks, special=special))
            parts = stripped.split(maxsplit=2)
            current_name = parts[1]
            current_chunks = [parts[2] if len(parts) > 2 else ""]
        elif current_name:
            current_chunks.append(stripped)
    return nets


def _net_from_chunks(name: str, chunks: list[str], *, special: bool) -> DefNet:
    text = " ".join(chunks)
    connection_text = re.split(r"\+\s+(?:ROUTED|FIXED|COVER|NEW)\b", text, maxsplit=1)[0]
    pins = [
        {"instance": inst, "pin_name": pin, "net": name, "source": "def_net_connections"}
        for inst, pin in _PIN_RE.findall(connection_text)
        if not _looks_numeric(inst) and not _looks_numeric(pin) and "*" not in {inst, pin}
    ]
    wires = _parse_routed_wires(name, text, special=special)
    return DefNet(name=name, pins=pins, wires=wires, special=special)


def _looks_numeric(value: str) -> bool:
    try:
        float(value)
    except ValueError:
        return False
    return True


def _parse_routed_wires(net_name: str, text: str, *, special: bool) -> list[DefWire]:
    wires: list[DefWire] = []
    tokens = re.split(r"\b(?:ROUTED|NEW)\b", text)
    for chunk in tokens[1:]:
        parts = chunk.strip().rstrip(";")
        if not parts:
            continue
        layer_match = re.match(r"(\S+)(?:\s+(\d+(?:\.\d+)?))?", parts)
        if not layer_match:
            continue
        layer = layer_match.group(1)
        width = float(layer_match.group(2)) if layer_match.group(2) else None
        points = _POINT_RE.findall(parts)
        if not points:
            continue
        via = _extract_via(parts, points[-1])
        previous: tuple[float, float] | None = None
        for raw_x, raw_y in points:
            if previous is None:
                if raw_x == "*" or raw_y == "*":
                    continue
                previous = (float(raw_x), float(raw_y))
                continue
            x = previous[0] if raw_x == "*" else float(raw_x)
            y = previous[1] if raw_y == "*" else float(raw_y)
            if (x, y) != previous:
                wires.append(DefWire(net=net_name, layer=layer, x1=previous[0], y1=previous[1], x2=x, y2=y, width=width, special=special))
            previous = (x, y)
        if via and previous:
            wires.append(DefWire(net=net_name, layer=layer, x1=previous[0], y1=previous[1], x2=previous[0], y2=previous[1], width=width, via=via, special=special))
    return wires


def _extract_via(chunk: str, last_point: tuple[str, str]) -> str | None:
    tail = chunk.rsplit(f"( {last_point[0]} {last_point[1]} )", 1)[-1]
    match = re.search(r"\b([A-Za-z_][A-Za-z0-9_.$-]*(?:VIA|via)[A-Za-z0-9_.$-]*)\b", tail)
    return match.group(1) if match else None
