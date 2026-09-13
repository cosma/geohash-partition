"""Draw docs/images/geohash-grid.svg with GeohashPartition's own geohash functions.

Left: a precision-5 geohash split into its 32 precision-6 cells.
Right: the 3 x 3 grid of precision-6 geohashes around one point.
Everything is drawn to scale in metres. Run from the repository root::

    uv run python docs/make_geohash_figure.py
"""

from __future__ import annotations

import math
import os

from geohash_partition.geohash import BASE32, bbox, encode, neighbors

LAT, LON = 52.5163, 13.3777  # Brandenburg Gate, Berlin
PLACE = "Brandenburg Gate, Berlin"
FINE = 6

INK = "#1e2a24"
MUTED = "#6b7a72"
LINE = "#a9b5ae"
CARD = "#fafbf8"
CARD_EDGE = "#dfe5e0"
ACCENT = "#2c6aa3"
ACCENT_TINT = "#d3e3f2"
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"
SANS = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"

M_PER_DEG_LAT = 110_574.0
M_PER_DEG_LON = 111_320.0 * math.cos(math.radians(LAT))


def projector(north: float, west: float, scale: float, x0: float, y0: float):
    def project(lat: float, lon: float):
        return x0 + (lon - west) * M_PER_DEG_LON * scale, y0 + (north - lat) * M_PER_DEG_LAT * scale
    return project


def box_px(code: str, project):
    min_lat, min_lon, max_lat, max_lon = bbox(code)
    x1, y1 = project(max_lat, min_lon)
    x2, y2 = project(min_lat, max_lon)
    return x1, y1, x2 - x1, y2 - y1


def fmt_m(metres: float) -> str:
    return f"{metres / 1000:.1f} km" if metres >= 1000 else f"{metres:,.0f} m"


def main() -> None:
    cell = encode(LAT, LON, FINE)
    parent = cell[:-1]
    parts = []

    # ---- left panel: parent split into 32 children -------------------------
    p_min_lat, p_min_lon, p_max_lat, p_max_lon = bbox(parent)
    parent_h_m = (p_max_lat - p_min_lat) * M_PER_DEG_LAT
    parent_w_m = (p_max_lon - p_min_lon) * M_PER_DEG_LON
    left_x, top = 40.0, 96.0
    left_scale = 336.0 / parent_h_m
    project_left = projector(p_max_lat, p_min_lon, left_scale, left_x, top)
    left_w = parent_w_m * left_scale

    parts.append(f'<text x="{left_x}" y="44" font-family="{SANS}" font-size="17" font-weight="600" fill="{INK}">'
                 f'<tspan font-family="{MONO}">{parent}</tspan> · precision {FINE - 1}</text>')
    parts.append(f'<text x="{left_x}" y="68" font-family="{SANS}" font-size="13" fill="{MUTED}">'
                 f'splits into 32 cells, one per extra character</text>')
    for char in BASE32:
        child = parent + char
        x, y, w, h = box_px(child, project_left)
        is_cell = child == cell
        fill = ACCENT_TINT if is_cell else CARD
        stroke = ACCENT if is_cell else LINE
        width = 2 if is_cell else 1
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{fill}" stroke="{stroke}" stroke-width="{width}"/>')
        parts.append(f'<text x="{x + w / 2:.1f}" y="{y + h / 2 + 5:.1f}" text-anchor="middle" font-family="{MONO}" '
                     f'font-size="14" font-weight="{700 if is_cell else 400}" fill="{ACCENT if is_cell else INK}">{char}</text>')
    parts.append(f'<rect x="{left_x:.1f}" y="{top:.1f}" width="{left_w:.1f}" height="336" fill="none" stroke="{INK}" stroke-width="1.5"/>')
    parts.append(f'<text x="{left_x}" y="{top + 336 + 24:.1f}" font-family="{SANS}" font-size="12" fill="{MUTED}">'
                 f'{fmt_m(parent_w_m)} × {fmt_m(parent_h_m)}</text>')

    # ---- right panel: 3 x 3 grid around the point ---------------------------
    around = neighbors(cell)
    rows = [
        [neighbors(around["n"])["w"], around["n"], neighbors(around["n"])["e"]],
        [around["w"], cell, around["e"]],
        [neighbors(around["s"])["w"], around["s"], neighbors(around["s"])["e"]],
    ]
    nw_min_lat, nw_min_lon, nw_max_lat, _ = bbox(rows[0][0])
    _, _, _, se_max_lon = bbox(rows[2][2])
    se_min_lat = bbox(rows[2][2])[0]
    grid_w_m = (se_max_lon - nw_min_lon) * M_PER_DEG_LON
    grid_h_m = (nw_max_lat - se_min_lat) * M_PER_DEG_LAT
    right_x = left_x + left_w + 96
    right_scale = 336.0 / grid_h_m
    project_right = projector(nw_max_lat, nw_min_lon, right_scale, right_x, top)
    right_w = grid_w_m * right_scale

    parts.append(f'<text x="{right_x:.1f}" y="44" font-family="{SANS}" font-size="17" font-weight="600" fill="{INK}">'
                 f'<tspan font-family="{MONO}">{cell}</tspan> and its 8 neighbours</text>')
    parts.append(f'<text x="{right_x:.1f}" y="68" font-family="{SANS}" font-size="13" fill="{MUTED}">'
                 f'precision {FINE} around the {PLACE}</text>')
    for r, row in enumerate(rows):
        for c, code in enumerate(row):
            x, y, w, h = box_px(code, project_right)
            is_cell = code == cell
            parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
                         f'fill="{ACCENT_TINT if is_cell else CARD}" stroke="{ACCENT if is_cell else LINE}" stroke-width="{2 if is_cell else 1}"/>')
            shared = len(os.path.commonprefix([code, parent]))
            label = (f'<tspan fill="{MUTED}">{code[:shared]}</tspan>'
                     f'<tspan fill="{ACCENT if is_cell else INK}" font-weight="700">{code[shared:]}</tspan>')
            parts.append(f'<text x="{x + w / 2:.1f}" y="{y + h / 2 + 5:.1f}" text-anchor="middle" font-family="{MONO}" font-size="15">{label}</text>')
    parts.append(f'<rect x="{right_x:.1f}" y="{top:.1f}" width="{right_w:.1f}" height="336" fill="none" stroke="{INK}" stroke-width="1.5"/>')

    px, py = project_right(LAT, LON)
    parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="5" fill="{INK}" stroke="{CARD}" stroke-width="2"/>')
    parts.append(f'<text x="{px + 10:.1f}" y="{py + 18:.1f}" font-family="{MONO}" font-size="12" fill="{INK}" '
                 f'stroke="{ACCENT_TINT}" stroke-width="4" paint-order="stroke">{LAT}, {LON}</text>')
    fine_w_m = (bbox(cell)[3] - bbox(cell)[1]) * M_PER_DEG_LON
    fine_h_m = (bbox(cell)[2] - bbox(cell)[0]) * M_PER_DEG_LAT
    parts.append(f'<text x="{right_x:.1f}" y="{top + 336 + 24:.1f}" font-family="{SANS}" font-size="12" fill="{MUTED}">'
                 f'each cell about {fmt_m(fine_w_m)} × {fmt_m(fine_h_m)} · grey part = shared prefix <tspan font-family="{MONO}">{parent}</tspan></text>')

    width = right_x + right_w + 40
    height = top + 336 + 48
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" width="{width:.0f}" height="{height:.0f}" '
           f'role="img" aria-label="Geohash {parent} split into 32 precision-{FINE} cells, and the 3 by 3 grid around {cell} at the {PLACE}">'
           f'<rect x="0.5" y="0.5" width="{width - 1:.0f}" height="{height - 1:.0f}" rx="12" fill="{CARD}" stroke="{CARD_EDGE}"/>'
           + "".join(parts) + "</svg>\n")
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images", "geohash-grid.svg")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as handle:
        handle.write(svg)
    print(f"wrote {out} ({width:.0f} x {height:.0f}); cell {cell}, parent {parent}; grid rows: {rows}")


if __name__ == "__main__":
    main()
