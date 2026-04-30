from __future__ import annotations


def resize_nearest(matrix: list[list[float]], rows: int, cols: int) -> list[list[float]]:
    if rows <= 0 or cols <= 0:
        return []
    src_rows = len(matrix)
    src_cols = max((len(row) for row in matrix), default=0)
    if src_rows == 0 or src_cols == 0:
        return [[0.0 for _ in range(cols)] for _ in range(rows)]
    out: list[list[float]] = []
    for row_index in range(rows):
        src_row = min(src_rows - 1, int(row_index * src_rows / rows))
        source = matrix[src_row]
        out_row: list[float] = []
        for col_index in range(cols):
            src_col = min(len(source) - 1, int(col_index * len(source) / cols)) if source else 0
            out_row.append(float(source[src_col]) if source else 0.0)
        out.append(out_row)
    return out


def build_patch_grid(rows: int, cols: int, die_bbox: dict[str, float] | None = None) -> dict:
    rows = max(1, int(rows or 1))
    cols = max(1, int(cols or 1))
    bbox = die_bbox or {"llx": 0.0, "lly": 0.0, "urx": float(cols), "ury": float(rows)}
    llx = float(bbox.get("llx", 0.0))
    lly = float(bbox.get("lly", 0.0))
    urx = float(bbox.get("urx", cols))
    ury = float(bbox.get("ury", rows))
    width = (urx - llx) / cols if cols else 0.0
    height = (ury - lly) / rows if rows else 0.0
    patches = []
    for row in range(rows):
        for col in range(cols):
            patch_llx = llx + col * width
            patch_lly = lly + row * height
            patches.append(
                {
                    "patch_id": row * cols + col,
                    "row": row,
                    "col": col,
                    "bbox": {
                        "llx": patch_llx,
                        "lly": patch_lly,
                        "urx": patch_llx + width,
                        "ury": patch_lly + height,
                    },
                }
            )
    return {"rows": rows, "cols": cols, "die_bbox": bbox, "patches": patches}
