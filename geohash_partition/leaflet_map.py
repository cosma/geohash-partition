"""Static interactive map of a partition, rendered with Leaflet.

The output is one self-contained HTML file: the areas are embedded as GeoJSON,
Leaflet is loaded from the jsDelivr CDN with Subresource Integrity, and base
map tiles come from OpenStreetMap. Open it in any browser. No server and no
Python packages are needed.
"""

from __future__ import annotations

import html
import json
import os
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

from .geohash import center
from .geojson import feature_collection, result_dict_to_geojson
from .style import SEQUENTIAL_BLUE

LEAFLET_VERSION = "1.9.4"
LEAFLET_CSS = f"https://cdn.jsdelivr.net/npm/leaflet@{LEAFLET_VERSION}/dist/leaflet.css"
LEAFLET_JS = f"https://cdn.jsdelivr.net/npm/leaflet@{LEAFLET_VERSION}/dist/leaflet.js"
LEAFLET_CSS_SRI = "sha384-sHL9NAb7lN7rfvG5lfHpm643Xkcjzp4jFvuavGOndn6pjVqS6ny56CAt3nsEVT4H"
LEAFLET_JS_SRI = "sha384-cxOPjt7s7Iz04uaHJceBmS+qpjv2JkIHNVcuOrM+YHwZOmJGBXI00mdUXEq65HTH"
DEFAULT_TITLE = "GeohashPartition map"

# Base map tile presets. Each entry is passed to L.tileLayer as-is.
TILE_PRESETS: Dict[str, Dict[str, Any]] = {
    "osm": {
        "url": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "maxZoom": 19,
        "attribution": '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    },
    "opentopomap": {
        "url": "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
        "subdomains": "abc",
        "maxZoom": 17,
        "attribution": (
            'Map data: &copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, SRTM'
            ' | Map style: &copy; <a href="https://opentopomap.org">OpenTopoMap</a>'
            ' (<a href="https://creativecommons.org/licenses/by-sa/3.0/">CC-BY-SA</a>)'
        ),
    },
}
# OpenStreetMap's servers require browsers to send a Referer header. A map
# opened straight from disk (file://) cannot send one and gets "Access blocked"
# tiles, so "auto" switches to a provider that accepts such requests.
AUTO_TILES = "osm"
FILE_FALLBACK_TILES = "opentopomap"


def resolve_tiles(tiles: str = "auto", attribution: Optional[str] = None) -> Dict[str, Any]:
    """Tile settings for the page: ``{"primary": {...}, "fileFallback": {...} or None}``.

    ``tiles`` is ``"auto"`` (OpenStreetMap, or OpenTopoMap when the file is opened
    from disk), a preset name from :data:`TILE_PRESETS`, or a tile URL template
    such as ``https://example.com/{z}/{x}/{y}.png`` (``attribution`` required).
    """
    if tiles == "auto":
        return {"primary": dict(TILE_PRESETS[AUTO_TILES]), "fileFallback": dict(TILE_PRESETS[FILE_FALLBACK_TILES])}
    if tiles in TILE_PRESETS:
        layer = dict(TILE_PRESETS[tiles])
        if attribution:
            layer["attribution"] = attribution
        return {"primary": layer, "fileFallback": None}
    if "{z}" in tiles and "{x}" in tiles and "{y}" in tiles:
        if not attribution:
            raise ValueError("a custom tile URL needs an attribution, e.g. '&copy; My Tiles'")
        return {"primary": {"url": tiles, "maxZoom": 19, "attribution": attribution}, "fileFallback": None}
    raise ValueError(
        f"unknown tiles {tiles!r}; use 'auto', one of {sorted(TILE_PRESETS)}, or a URL template with {{z}}, {{x}} and {{y}}"
    )


MapSource = Union[Mapping[str, Any], Any]

CONFIG_LABELS: Sequence[Tuple[str, str]] = (
    ("min_area_weight", "Min area weight"),
    ("max_area_weight", "Max area weight"),
    ("max_grids_per_area", "Max grids per area"),
    ("precision", "Precision"),
    ("greediness", "Greediness"),
    ("max_areas", "Max areas"),
    ("max_failures", "Max failures"),
    ("fill_holes", "Fill holes"),
    ("seed_order", "Seed order"),
    ("random_seed", "Random seed"),
)


def _fmt(value: Any) -> str:
    if value is None:
        return "none"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        if value.is_integer():
            return f"{int(value):,}"
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    return str(value)


def load(path: str) -> Dict[str, Any]:
    """Read a saved result (``.json``) or a FeatureCollection (``.geojson``)."""
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _split(source: MapSource, include_leftover: bool) -> Tuple[Dict[str, Any], Dict[str, Any], List[dict], List[dict]]:
    """Return ``(config, stats, area_features, leftover_features)`` for any supported source."""
    if hasattr(source, "to_geojson") and hasattr(source, "config"):
        result: Any = source
        collection = result.to_geojson(include_leftover=include_leftover)
        config, stats = result.config.to_dict(), dict(result.stats)
    elif isinstance(source, Mapping) and source.get("type") == "FeatureCollection":
        collection, config, stats = source, {}, {}
    elif isinstance(source, Mapping) and "areas" in source:
        collection = result_dict_to_geojson(source, include_leftover=include_leftover)
        config, stats = dict(source.get("config", {})), dict(source.get("stats", {}))
    else:
        raise ValueError("expected a PartitionResult, a saved result dict, or a GeoJSON FeatureCollection")

    areas, leftover = [], []
    for feature in collection.get("features", []):
        kind = feature.get("properties", {}).get("kind", "area")
        if kind == "leftover":
            if include_leftover:
                leftover.append(feature)
        else:
            areas.append(feature)
    return config, stats, areas, leftover


def _stats_rows(stats: Mapping[str, Any], areas: List[dict], leftover: List[dict]) -> List[List[str]]:
    count = len(areas)
    grouped_grids = stats.get(
        "grouped_grids",
        sum(f["properties"].get("grid_count", 0) - f["properties"].get("empty_grids", 0) for f in areas),
    )
    grouped_weight = stats.get("grouped_weight", sum(f["properties"].get("weight", 0) for f in areas))
    rows = [["Areas", _fmt(stats.get("total_areas", count))]]
    if "total_grids" in stats:
        rows.append(["Grids grouped", f"{_fmt(grouped_grids)} of {_fmt(stats['total_grids'])}"])
    else:
        rows.append(["Grids grouped", _fmt(grouped_grids)])
    rows.append(["Grids left over", _fmt(stats.get("leftover_grids", len(leftover)))])
    if count:
        rows.append(["Average weight per area", _fmt(round(float(grouped_weight) / count, 1))])
        rows.append(["Average grids per area", _fmt(round(float(grouped_grids) / count, 1))])
    labels = (
        ("rejected_seeds", "Rejected seeds"),
        ("absorbed_grids", "Grids absorbed"),
        ("filled_grids", "Leftover grids filled into gaps"),
        ("empty_grids_filled", "Empty grids filled into gaps"),
    )
    for key, label in labels:
        if key in stats:
            rows.append([label, _fmt(stats[key])])
    if "duration_seconds" in stats:
        rows.append(["Duration", f"{_fmt(stats['duration_seconds'])} s"])
    return rows


def build_payload(
    source: MapSource,
    title: Optional[str] = None,
    include_leftover: bool = True,
    tiles: str = "auto",
    tiles_attribution: Optional[str] = None,
) -> Dict[str, Any]:
    """Everything the HTML page needs, as one JSON-serialisable dict."""
    tile_settings = resolve_tiles(tiles, tiles_attribution)
    config, stats, areas, leftover = _split(source, include_leftover)
    seeds = []
    for feature in areas:
        props = feature["properties"]
        seed = props.get("seed")
        if seed:
            lat, lon = center(seed)
            seeds.append({"id": seed, "area_id": props.get("area_id", seed), "lat": lat, "lon": lon})
    return {
        "title": title or DEFAULT_TITLE,
        "areas": feature_collection(areas),
        "leftover": feature_collection(leftover),
        "seeds": seeds,
        "statsRows": _stats_rows(stats, areas, leftover),
        "configRows": [[label, _fmt(config[key])] for key, label in CONFIG_LABELS if key in config],
        "limits": {
            "minWeight": config.get("min_area_weight"),
            "maxWeight": config.get("max_area_weight"),
            "maxGrids": config.get("max_grids_per_area"),
        },
        "ramp": list(SEQUENTIAL_BLUE),
        "tiles": tile_settings,
    }


def render_map(
    source: MapSource,
    title: Optional[str] = None,
    include_leftover: bool = True,
    tiles: str = "auto",
    tiles_attribution: Optional[str] = None,
) -> str:
    """Return the map as an HTML string. See :func:`resolve_tiles` for ``tiles``."""
    payload = build_payload(
        source, title=title, include_leftover=include_leftover, tiles=tiles, tiles_attribution=tiles_attribution
    )
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    data = data.replace("</", "<\\/").replace("<!--", "<\\!--")
    replacements = {
        "__TITLE__": html.escape(payload["title"]),
        "__LEAFLET_CSS__": LEAFLET_CSS,
        "__LEAFLET_CSS_SRI__": LEAFLET_CSS_SRI,
        "__LEAFLET_JS__": LEAFLET_JS,
        "__LEAFLET_JS_SRI__": LEAFLET_JS_SRI,
    }
    page = _TEMPLATE
    for key, value in replacements.items():
        page = page.replace(key, value)
    return page.replace("__DATA__", data)


def save_map(
    source: MapSource,
    path: str,
    title: Optional[str] = None,
    include_leftover: bool = True,
    tiles: str = "auto",
    tiles_attribution: Optional[str] = None,
) -> str:
    """Write the map to ``path`` and return the path."""
    page = render_map(
        source, title=title, include_leftover=include_leftover, tiles=tiles, tiles_attribution=tiles_attribution
    )
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(page)
    return path


_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<link rel="stylesheet" href="__LEAFLET_CSS__" integrity="__LEAFLET_CSS_SRI__" crossorigin="anonymous">
<script src="__LEAFLET_JS__" integrity="__LEAFLET_JS_SRI__" crossorigin="anonymous"></script>
<style>
  :root {
    --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e; --muted: #898781;
    --hairline: #e1e0d9; --axis: #c3c2b7; --series: #2a78d6; --series-strong: #0d366b;
  }
  html, body { height: 100%; margin: 0; }
  body { font: 13px/1.45 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; color: var(--ink); background: var(--surface); }
  #map { position: absolute; inset: 0; }
  .gp-panel {
    position: absolute; z-index: 1000; left: 16px; bottom: 28px; width: 320px;
    max-width: calc(100vw - 32px); max-height: calc(100vh - 110px); overflow: auto;
    background: var(--surface); border: 1px solid var(--hairline); border-radius: 8px;
    box-shadow: 0 2px 12px rgba(0, 0, 0, .16);
  }
  .gp-panel header {
    position: sticky; top: 0; display: flex; align-items: center; justify-content: space-between; gap: 8px;
    padding: 10px 12px; background: var(--surface); border-bottom: 1px solid var(--hairline);
  }
  .gp-panel h1 { margin: 0; font-size: 14px; font-weight: 600; }
  .gp-toggle {
    flex: none; padding: 2px 10px; border: 1px solid var(--axis); border-radius: 6px;
    background: transparent; color: var(--ink-2); font: inherit; cursor: pointer;
  }
  .gp-toggle:focus-visible { outline: 2px solid var(--series); outline-offset: 2px; }
  .gp-body { padding: 4px 12px 12px; }
  .gp-panel.collapsed .gp-body { display: none; }
  .gp-panel.collapsed header { border-bottom: 0; }
  .gp-panel h2 { margin: 12px 0 4px; font-size: 11px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase; color: var(--muted); }
  .gp-kv { width: 100%; border-collapse: collapse; }
  .gp-kv td { padding: 1px 0; vertical-align: top; }
  .gp-kv td:first-child { color: var(--ink-2); padding-right: 12px; }
  .gp-kv td:last-child { text-align: right; font-variant-numeric: tabular-nums; }
  .gp-ramp { height: 10px; border-radius: 4px; }
  .gp-ramp-labels { display: flex; justify-content: space-between; color: var(--ink-2); font-variant-numeric: tabular-nums; }
  .gp-hist svg { display: block; width: 100%; height: auto; overflow: visible; }
  .gp-hist .bar { fill: var(--series); }
  .gp-hist .bar:hover { fill: var(--series-strong); }
  .gp-hist .base { stroke: var(--axis); }
  .gp-hist .limit { stroke: var(--muted); stroke-dasharray: 3 3; }
  .gp-hist text { fill: var(--muted); font-size: 10px; font-variant-numeric: tabular-nums; }
  .gp-popup td { padding: 1px 0; }
  .gp-popup td:first-child { color: var(--ink-2); padding-right: 10px; }
  .gp-popup td:last-child { font-variant-numeric: tabular-nums; }
  .gp-grids {
    margin-top: 6px; max-width: 260px; max-height: 96px; overflow: auto; color: var(--ink-2);
    font: 11px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace; word-break: break-all;
  }
</style>
</head>
<body>
<div id="map" role="region" aria-label="Map of areas"></div>
<aside class="gp-panel" id="panel" aria-label="Partition summary">
  <header>
    <h1 id="title"></h1>
    <button type="button" class="gp-toggle" id="toggle" aria-expanded="true" aria-controls="panel-body">Hide</button>
  </header>
  <div class="gp-body" id="panel-body">
    <h2>Area weight</h2>
    <div class="gp-ramp" id="ramp"></div>
    <div class="gp-ramp-labels"><span id="ramp-low"></span><span id="ramp-high"></span></div>
    <h2>Outcome</h2>
    <table class="gp-kv" id="stats"></table>
    <h2 id="config-heading">Parameters</h2>
    <table class="gp-kv" id="config"></table>
    <h2>Weight per area</h2>
    <div class="gp-hist" id="hist-weight"></div>
    <h2>Grids per area</h2>
    <div class="gp-hist" id="hist-grids"></div>
  </div>
</aside>
<script>
const DATA = __DATA__;
(function () {
  "use strict";
  const SVG = "http://www.w3.org/2000/svg";
  const numberFormat = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 });
  const num = (value) => (typeof value === "number" ? numberFormat.format(value) : String(value));
  const byId = (id) => document.getElementById(id);

  function textEl(text) {
    const span = document.createElement("span");
    span.textContent = text;
    return span;
  }

  function fillTable(table, rows) {
    for (const [label, value] of rows) {
      const tr = document.createElement("tr");
      const key = document.createElement("td");
      const val = document.createElement("td");
      key.textContent = label;
      val.textContent = value;
      tr.append(key, val);
      table.append(tr);
    }
  }

  // ---- panel -------------------------------------------------------------
  byId("title").textContent = DATA.title;
  fillTable(byId("stats"), DATA.statsRows);
  if (DATA.configRows.length) fillTable(byId("config"), DATA.configRows);
  else { byId("config-heading").hidden = true; byId("config").hidden = true; }

  const panel = byId("panel");
  const toggle = byId("toggle");
  toggle.addEventListener("click", () => {
    const collapsed = panel.classList.toggle("collapsed");
    toggle.textContent = collapsed ? "Show" : "Hide";
    toggle.setAttribute("aria-expanded", String(!collapsed));
  });
  if (window.innerWidth < 640) toggle.click();

  const areaProps = DATA.areas.features.map((feature) => feature.properties);
  const weights = areaProps.map((p) => p.weight);
  const gridCounts = areaProps.map((p) => p.grid_count);
  const low = weights.reduce((a, b) => Math.min(a, b), Infinity);
  const high = weights.reduce((a, b) => Math.max(a, b), -Infinity);
  byId("ramp").style.background = "linear-gradient(90deg," + DATA.ramp.join(",") + ")";
  byId("ramp-low").textContent = weights.length ? num(low) : "";
  byId("ramp-high").textContent = weights.length ? num(high) : "";

  // ---- map ---------------------------------------------------------------
  const map = L.map("map", { preferCanvas: true });
  // OpenStreetMap blocks tile requests without a Referer, which a page opened
  // from disk cannot send; use the fallback provider in that case.
  const openedFromDisk = window.location.protocol === "file:";
  const tiles = (openedFromDisk && DATA.tiles.fileFallback) || DATA.tiles.primary;
  L.tileLayer(tiles.url, Object.assign({ referrerPolicy: "strict-origin-when-cross-origin" }, tiles)).addTo(map);
  L.control.scale({ position: "bottomright" }).addTo(map);

  const styleOf = (feature) => {
    const p = feature.properties;
    return {
      color: p.stroke, weight: p["stroke-width"], opacity: p["stroke-opacity"],
      fillColor: p.fill, fillOpacity: p["fill-opacity"],
    };
  };

  function areaPopup(p) {
    const box = document.createElement("div");
    box.className = "gp-popup";
    const table = document.createElement("table");
    const rows = [["Area", p.area_id], ["Weight", num(p.weight)], ["Grids", num(p.grid_count)]];
    if (p.empty_grids) rows.push(["Empty grids filled", num(p.empty_grids)]);
    rows.push(["Seed", p.seed]);
    fillTable(table, rows);
    const grids = document.createElement("div");
    grids.className = "gp-grids";
    grids.textContent = String(p.grids || "").split(",").join(" ");
    box.append(table, grids);
    return box;
  }

  const areas = L.geoJSON(DATA.areas, {
    style: styleOf,
    onEachFeature(feature, layer) {
      const p = feature.properties;
      layer.bindTooltip(textEl(p.area_id + " · weight " + num(p.weight) + " · " + num(p.grid_count) + " grids"), { sticky: true });
      layer.bindPopup(() => areaPopup(p));
      layer.on({
        mouseover(event) { event.target.setStyle({ weight: 2.5, fillOpacity: 0.78 }); event.target.bringToFront(); },
        mouseout(event) { areas.resetStyle(event.target); },
      });
    },
  }).addTo(map);

  const leftover = L.geoJSON(DATA.leftover, {
    style: styleOf,
    onEachFeature(feature, layer) {
      const p = feature.properties;
      layer.bindTooltip(textEl(p.grid + " · weight " + num(p.weight) + " · in no area"), { sticky: true });
    },
  });

  const seeds = L.layerGroup(DATA.seeds.map((seed) =>
    L.circleMarker([seed.lat, seed.lon], { radius: 4, color: "#fcfcfb", weight: 2, fillColor: "#0d366b", fillOpacity: 1 })
      .bindTooltip(textEl("seed of area " + seed.area_id))
  ));

  const overlays = { ["Areas (" + num(DATA.areas.features.length) + ")"]: areas };
  if (DATA.leftover.features.length) overlays["Leftover grids (" + num(DATA.leftover.features.length) + ")"] = leftover;
  if (DATA.seeds.length) overlays["Seeds"] = seeds;
  L.control.layers(null, overlays, { collapsed: window.innerWidth < 640 }).addTo(map);

  const bounds = areas.getBounds();
  // keep the areas clear of the side panel when there is room for both
  const panelGap = window.innerWidth >= 900 ? panel.offsetWidth + 32 : 24;
  if (bounds.isValid()) map.fitBounds(bounds, { paddingTopLeft: [panelGap, 24], paddingBottomRight: [24, 24] });
  else if (DATA.leftover.features.length) map.fitBounds(leftover.getBounds());
  else map.setView([20, 0], 2);

  // ---- histograms --------------------------------------------------------
  function histogram(container, values, limits, unit) {
    if (!values.length) { container.textContent = "No areas formed."; return; }
    const finite = limits.filter((v) => typeof v === "number" && isFinite(v));
    let lo = Math.min(values.reduce((a, b) => Math.min(a, b), Infinity), ...finite);
    let hi = Math.max(values.reduce((a, b) => Math.max(a, b), -Infinity), ...finite);
    if (hi === lo) hi = lo + 1;
    const bins = Math.max(1, Math.min(24, Math.ceil(Math.sqrt(values.length))));
    const step = (hi - lo) / bins;
    const counts = new Array(bins).fill(0);
    for (const v of values) counts[Math.min(bins - 1, Math.floor((v - lo) / step))] += 1;
    const peak = Math.max(...counts);

    const W = 296, H = 92, top = 14, base = 72;
    const x = (v) => ((v - lo) / (hi - lo)) * W;
    const svg = document.createElementNS(SVG, "svg");
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "Histogram of " + unit + " per area");

    const add = (name, attrs, text) => {
      const el = document.createElementNS(SVG, name);
      for (const k in attrs) el.setAttribute(k, attrs[k]);
      if (text !== undefined) el.textContent = text;
      svg.append(el);
      return el;
    };

    counts.forEach((count, i) => {
      if (!count) return;
      const x0 = x(lo + i * step) + 1, width = Math.max(1, W / bins - 2);
      const height = Math.max(2, (count / peak) * (base - top));
      const y = base - height, r = Math.min(3, width / 2, height);
      const d = "M" + x0 + "," + base + "V" + (y + r) + "Q" + x0 + "," + y + " " + (x0 + r) + "," + y +
        "H" + (x0 + width - r) + "Q" + (x0 + width) + "," + y + " " + (x0 + width) + "," + (y + r) + "V" + base + "Z";
      const bar = add("path", { d, class: "bar" });
      const tip = document.createElementNS(SVG, "title");
      tip.textContent = num(lo + i * step) + " to " + num(lo + (i + 1) * step) + " " + unit + ": " + count + (count === 1 ? " area" : " areas");
      bar.append(tip);
    });
    add("line", { x1: 0, x2: W, y1: base + 0.5, y2: base + 0.5, class: "base" });
    [["min", limits[0]], ["max", limits[1]]].forEach(([label, value]) => {
      if (typeof value !== "number" || !isFinite(value)) return;
      const px = x(value);
      add("line", { x1: px, x2: px, y1: top - 4, y2: base, class: "limit" });
      add("text", { x: px, y: top - 6, "text-anchor": label === "min" ? "start" : "end" }, label + " " + num(value));
    });
    add("text", { x: 0, y: H - 4 }, num(lo));
    add("text", { x: W, y: H - 4, "text-anchor": "end" }, num(hi));
    add("text", { x: W / 2, y: H - 4, "text-anchor": "middle" }, "tallest bar " + peak + (peak === 1 ? " area" : " areas"));
    container.append(svg);
  }

  histogram(byId("hist-weight"), weights, [DATA.limits.minWeight, DATA.limits.maxWeight], "weight");
  histogram(byId("hist-grids"), gridCounts, [null, DATA.limits.maxGrids], "grids");
})();
</script>
</body>
</html>
"""
