// NAD+ viewer: the published PMTiles for zoom 10+ and a county coverage overlay below.
// ?data=<base url> points the page at another copy of the files (e.g. a local test server).

const params = new URLSearchParams(location.search);
const DATA = (params.get("data") || "https://nad.watmildon.org").replace(/\/$/, "");
const TILES = `${DATA}/nad-current.pmtiles`;
const COVERAGE = `${DATA}/nad-current-coverage.geojson`;
const SIDECAR = `${DATA}/nad-current.json`;

const POINT_ZOOM = 10;  // first zoom in the tileset
const FULL_ZOOM = 14;   // zoom at which every point is present
const LABEL_ZOOM = 17;
// Counties with fewer points than this are outlined but not filled: they are mostly a few
// points that strayed over a county line, and a full fill would read as coverage.
const SPARSE = 100;

const dark = matchMedia("(prefers-color-scheme: dark)").matches;
const css = getComputedStyle(document.documentElement);
const color = (name) => css.getPropertyValue(name).trim();
const COLORS = { nad: color("--nad"), mixed: color("--mixed"), other: color("--other") };
const fmt = new Intl.NumberFormat("en-US");

const STATES = {
  AL: "Alabama", AK: "Alaska", AZ: "Arizona", AR: "Arkansas", CA: "California",
  CO: "Colorado", CT: "Connecticut", DE: "Delaware", DC: "District of Columbia",
  FL: "Florida", GA: "Georgia", HI: "Hawaii", ID: "Idaho", IL: "Illinois", IN: "Indiana",
  IA: "Iowa", KS: "Kansas", KY: "Kentucky", LA: "Louisiana", ME: "Maine", MD: "Maryland",
  MA: "Massachusetts", MI: "Michigan", MN: "Minnesota", MS: "Mississippi", MO: "Missouri",
  MT: "Montana", NE: "Nebraska", NV: "Nevada", NH: "New Hampshire", NJ: "New Jersey",
  NM: "New Mexico", NY: "New York", NC: "North Carolina", ND: "North Dakota", OH: "Ohio",
  OK: "Oklahoma", OR: "Oregon", PA: "Pennsylvania", RI: "Rhode Island",
  SC: "South Carolina", SD: "South Dakota", TN: "Tennessee", TX: "Texas", UT: "Utah",
  VT: "Vermont", VA: "Virginia", WA: "Washington", WV: "West Virginia", WI: "Wisconsin",
  WY: "Wyoming", PR: "Puerto Rico", VI: "U.S. Virgin Islands", GU: "Guam",
  AS: "American Samoa", MP: "Northern Mariana Islands",
};

// ---- small DOM helpers -------------------------------------------------------------------

const $ = (id) => document.getElementById(id);

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function safeUrl(url) {
  try {
    const u = new URL(url);
    return u.protocol === "https:" || u.protocol === "http:" ? u.href : null;
  } catch {
    return null;
  }
}

const pct = (part, whole) => (whole ? Math.round((100 * part) / whole) : 0);

// ---- panel -------------------------------------------------------------------------------

const panel = $("panel");
const toggle = $("toggle");

function setCollapsed(collapsed) {
  panel.classList.toggle("collapsed", collapsed);
  toggle.setAttribute("aria-expanded", String(!collapsed));
  toggle.setAttribute("aria-label", collapsed ? "Show panel" : "Hide panel");
}

toggle.addEventListener("click", () => setCollapsed(!panel.classList.contains("collapsed")));
const narrow = matchMedia("(max-width: 640px)").matches;
if (narrow) setCollapsed(true);

// ---- map ---------------------------------------------------------------------------------

const protocol = new pmtiles.Protocol({ metadata: true });
maplibregl.addProtocol("pmtiles", protocol.tile);

const map = new maplibregl.Map({
  container: "map",
  style: `https://tiles.openfreemap.org/styles/${dark ? "dark" : "positron"}`,
  // The lower 48, framed beside the panel; a #map= hash in the URL takes precedence.
  bounds: [[-125, 24.5], [-66.9, 49.4]],
  fitBoundsOptions: { padding: sidePadding() },
  hash: "map",
  attributionControl: false,
});
map.addControl(new maplibregl.NavigationControl({ visualizePitch: false }), "top-right");

// The info box and scale bar in the lower right, rebuilt once the sidecar says when the data
// was built. One string, because MapLibre reorders separate attribution entries by length;
// the scale bar is re-added after the info box so it stays above it.
let attribution = null;
let scale = null;

function setAttribution(built) {
  const github = '<a href="https://github.com/watmildon/nad-endpoint">NAD+ on GitHub</a>';
  const text = built ? `${github} · data built ${esc(built)}` : github;
  if (attribution) map.removeControl(attribution);
  if (scale) map.removeControl(scale);
  attribution = new maplibregl.AttributionControl({ compact: true, customAttribution: text });
  scale = new maplibregl.ScaleControl({ unit: "imperial" });
  map.addControl(attribution);
  map.addControl(scale, "bottom-right");
}

setAttribution();

function sidePadding() {
  return narrow ? { top: 40, bottom: 80, left: 20, right: 20 }
    : { top: 40, bottom: 40, left: panel.offsetWidth + 40, right: 60 };
}

const coverage = { byGeoid: new Map(), sources: {} };

function byOrigin(nad, mixed, other) {
  return ["match", ["get", "origin"], "other", other, "mixed", mixed, nad];
}

map.on("load", () => {
  // Coverage sits under the basemap's labels; the points go on top of everything.
  const labels = map.getStyle().layers.find((l) => l.type === "symbol")?.id;

  map.addSource("coverage", {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
    promoteId: "geoid",
  });
  const hover = ["boolean", ["feature-state", "hover"], false];
  const sparse = ["<", ["get", "points"], SPARSE];
  // Every county stays in the fill layer, so sparse ones can still be hovered and clicked.
  const fill = (normal, hovered) => ["case", sparse, ["case", hover, 0.15, 0],
    ["case", hover, hovered, normal]];
  map.addLayer({
    id: "coverage-fill",
    type: "fill",
    source: "coverage",
    paint: {
      "fill-color": byOrigin(COLORS.nad, COLORS.mixed, COLORS.other),
      "fill-opacity": ["interpolate", ["linear"], ["zoom"],
        3, fill(0.42, 0.6), 9, fill(0.25, 0.4), POINT_ZOOM, 0.05],
    },
  }, labels);
  const lineWidth = ["interpolate", ["linear"], ["zoom"],
    3, ["case", hover, 2.5, 0.3], 8, ["case", hover, 2.5, 0.8], 12, 1.5];
  map.addLayer({
    id: "coverage-line",
    type: "line",
    source: "coverage",
    filter: [">=", ["get", "points"], SPARSE],
    paint: {
      "line-color": byOrigin(COLORS.nad, COLORS.mixed, COLORS.other),
      "line-opacity": 0.8,
      "line-width": lineWidth,
    },
  }, labels);
  map.addLayer({
    id: "coverage-sparse",
    type: "line",
    source: "coverage",
    filter: sparse,
    paint: {
      "line-color": byOrigin(COLORS.nad, COLORS.mixed, COLORS.other),
      "line-opacity": 0.9,
      "line-width": lineWidth,
      "line-dasharray": [2, 2],
    },
  }, labels);

  map.addSource("addresses", { type: "vector", url: `pmtiles://${TILES}` });
  map.addLayer({
    id: "points",
    type: "circle",
    source: "addresses",
    "source-layer": "addresses",
    minzoom: POINT_ZOOM,
    paint: {
      "circle-color": color("--point"),
      "circle-radius": ["interpolate", ["linear"], ["zoom"], 10, 1.2, 14, 2.6, 18, 6],
      "circle-stroke-color": dark ? "#111" : "#fff",
      "circle-stroke-width": ["interpolate", ["linear"], ["zoom"], 14, 0, 16, 1],
    },
  });
  map.addLayer({
    id: "housenumbers",
    type: "symbol",
    source: "addresses",
    "source-layer": "addresses",
    minzoom: LABEL_ZOOM,
    layout: {
      "text-field": ["get", "addr:housenumber"],
      "text-font": ["Noto Sans Regular"],
      "text-size": 11,
      "text-offset": [0, -1],
      "text-anchor": "bottom",
    },
    paint: {
      "text-color": dark ? "#f1f1f1" : "#3a1020",
      "text-halo-color": dark ? "#111" : "#fff",
      "text-halo-width": 1.2,
    },
  });

  loadCoverage();
  loadSidecar();
});

// ---- data --------------------------------------------------------------------------------

async function loadSidecar() {
  try {
    const res = await fetch(SIDECAR);
    if (!res.ok) throw new Error(res.status);
    const meta = await res.json();
    $("meta").textContent = `${fmt.format(meta.points)} address points`;
    setAttribution(meta.built);
  } catch {
    $("meta").textContent = "Point count unavailable";
  }
}

async function loadCoverage() {
  let data;
  try {
    const res = await fetch(COVERAGE);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    data = await res.json();
  } catch (err) {
    $("coverage-status").textContent =
      `The coverage overlay is not available (${err.message}). Address points still show from zoom ${POINT_ZOOM}.`;
    return;
  }
  map.getSource("coverage").setData(data);
  coverage.sources = data.sources || {};
  for (const f of data.features) coverage.byGeoid.set(f.properties.geoid, f.properties);

  renderStates(data);
  renderSources(data.release, coverage.sources);
  $("coverage-status").textContent = `${fmt.format(data.features.length)} counties hold points.`;
}

function renderStates(data) {
  const states = new Map();
  for (const f of data.features) {
    const p = f.properties;
    const s = states.get(p.state) || { points: 0, other: 0, ...emptyBounds() };
    s.points += p.points;
    s.other += p.other;
    eachCoordinate(f.geometry, ([x, y]) => extend(s, x, y));
    states.set(p.state, s);
  }

  const tbody = $("states").querySelector("tbody");
  tbody.replaceChildren();
  const codes = [...states.keys()].sort((a, b) => (STATES[a] || a).localeCompare(STATES[b] || b));
  for (const code of codes) {
    const s = states.get(code);
    const tr = document.createElement("tr");
    tr.tabIndex = 0;
    tr.innerHTML = `<td>${esc(STATES[code] || code)}</td>
      <td class="num">${fmt.format(s.points)}</td>
      <td class="num"><span class="share">${s.other ? `${pct(s.other, s.points) || "<1"}%` : "–"}</span></td>`;
    const go = () => flyToState(s);
    tr.addEventListener("click", go);
    tr.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
    tbody.append(tr);
  }
  $("states").hidden = false;

  const missing = Object.keys(STATES).filter((c) => !states.has(c)).map((c) => STATES[c]);
  if (missing.length) {
    $("no-data").textContent = `No points: ${missing.join(", ")}.`;
    $("no-data").hidden = false;
  }
}

const NAD_PAGE = "https://www.transportation.gov/gis/national-address-database";

function renderSources(release, sources) {
  const all = Object.values(sources);
  const nadPoints = all.filter((s) => s.kind === "nad").reduce((sum, s) => sum + s.points, 0);
  const extra = all.filter((s) => s.kind === "other");
  extra.sort((a, b) => (a.state + a.name).localeCompare(b.state + b.name));
  const item = (name, url, sub) => {
    const link = url ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(name)}</a>` : esc(name);
    return `<li>${link}<span class="sub">${sub}</span></li>`;
  };
  $("sources").innerHTML = [
    item("National Address Database", NAD_PAGE,
      `US Department of Transportation · release ${esc(release)} · public domain · ${fmt.format(nadPoints)} points`),
    ...extra.map((s) => item(s.name, safeUrl(s.page),
      `${esc(s.publisher)} · ${esc(s.licence)} · ${fmt.format(s.points)} points`)),
  ].join("");
  $("sources-section").hidden = false;
}

function eachCoordinate(geometry, fn) {
  const polygons = geometry.type === "Polygon" ? [geometry.coordinates] : geometry.coordinates;
  for (const polygon of polygons) for (const point of polygon[0]) fn(point);
}

// Bounds kept separately for each hemisphere so a state across the antimeridian (Alaska's
// Aleutians) can be framed from its west end rather than spanning the whole globe.
function emptyBounds() {
  return { west: [Infinity, -Infinity], east: [Infinity, -Infinity], south: Infinity, north: -Infinity };
}

function extend(b, x, y) {
  const side = x < 0 ? b.west : b.east;
  side[0] = Math.min(side[0], x);
  side[1] = Math.max(side[1], x);
  b.south = Math.min(b.south, y);
  b.north = Math.max(b.north, y);
}

function flyToState(s) {
  const hasWest = s.west[0] <= s.west[1];
  const hasEast = s.east[0] <= s.east[1];
  let w, e;
  if (hasWest && hasEast && s.west[1] < -100 && s.east[0] > 100) {
    [w, e] = [s.east[0] - 360, s.west[1]];
  } else {
    w = Math.min(hasWest ? s.west[0] : Infinity, hasEast ? s.east[0] : Infinity);
    e = Math.max(hasWest ? s.west[1] : -Infinity, hasEast ? s.east[1] : -Infinity);
  }
  if (narrow) setCollapsed(true);
  map.fitBounds([[w, s.south], [e, s.north]], { padding: sidePadding(), maxZoom: 11 });
}

// ---- interaction -------------------------------------------------------------------------

let hovered = null;

function setHover(id) {
  if (hovered === id) return;
  if (hovered !== null) map.setFeatureState({ source: "coverage", id: hovered }, { hover: false });
  hovered = id;
  if (id !== null) map.setFeatureState({ source: "coverage", id }, { hover: true });
}

map.on("mousemove", (e) => {
  if (!map.getLayer("points")) return;
  const points = map.getZoom() >= POINT_ZOOM && map.queryRenderedFeatures(box(e.point, 5), { layers: ["points"] });
  const county = map.getZoom() < POINT_ZOOM && map.queryRenderedFeatures(e.point, { layers: ["coverage-fill"] })[0];
  setHover(county ? county.properties.geoid : null);
  map.getCanvas().style.cursor = (points && points.length) || county ? "pointer" : "";
});

map.on("mouseout", () => setHover(null));

map.on("click", (e) => {
  if (!map.getLayer("points")) return;
  if (map.getZoom() >= POINT_ZOOM) {
    const points = map.queryRenderedFeatures(box(e.point, 6), { layers: ["points"] });
    if (points.length) {
      popup(e.lngLat, addressHtml(points));
      return;
    }
  }
  const county = map.queryRenderedFeatures(e.point, { layers: ["coverage-fill"] })[0];
  if (county) popup(e.lngLat, countyHtml(coverage.byGeoid.get(county.properties.geoid)));
});

function box(p, r) {
  return [[p.x - r, p.y - r], [p.x + r, p.y + r]];
}

function popup(lngLat, html) {
  const p = new maplibregl.Popup({ maxWidth: "320px" }).setLngLat(lngLat).setHTML(html).addTo(map);
  p.getElement().addEventListener("click", (e) => {
    const button = e.target.closest("button.copy");
    if (button) copyTags(button);
  });
}

// Tags go to the clipboard as key=value lines, which JOSM's tag paste and iD's text view take.
async function copyTags(button) {
  const text = button.dataset.tags;
  let ok = false;
  try {
    await navigator.clipboard.writeText(text);
    ok = true;
  } catch {
    // No async clipboard (an insecure origin, an older browser): fall back to a selection.
    const area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.opacity = "0";
    document.body.append(area);
    area.select();
    ok = document.execCommand("copy");
    area.remove();
  }
  const label = ok ? "Copied" : "Copy failed";
  button.classList.add(ok ? "done" : "failed");
  button.title = label;
  button.setAttribute("aria-label", label);
  setTimeout(() => {
    button.classList.remove("done", "failed");
    button.title = "Copy tags";
    button.setAttribute("aria-label", "Copy tags");
  }, 1500);
}

// Two overlapping squares, and the check mark shown briefly after a copy.
const COPY_ICON = `<svg class="icon-copy" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
  <rect x="5.5" y="5.5" width="8" height="8" rx="1.5" fill="none" stroke="currentColor" stroke-width="1.4"/>
  <path d="M10.5 3.5v-.5a1.5 1.5 0 0 0-1.5-1.5H4A1.5 1.5 0 0 0 2.5 3v5A1.5 1.5 0 0 0 4 9.5h.5" fill="none" stroke="currentColor" stroke-width="1.4"/>
</svg>`;
const DONE_ICON = `<svg class="icon-done" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
  <path d="M3.5 8.5l3 3 6-7" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>
</svg>`;

const TAG_ORDER = ["addr:housenumber", "addr:street", "addr:unit", "addr:city", "addr:state", "addr:postcode"];

function addressHtml(features) {
  // Units of one building share a position; show each distinct address once.
  const seen = new Set();
  const rows = [];
  for (const f of features) {
    const key = TAG_ORDER.map((t) => f.properties[t] || "").join("|");
    if (seen.has(key)) continue;
    seen.add(key);
    rows.push(f);
  }
  rows.sort((a, b) => (a.properties["addr:unit"] || "").localeCompare(b.properties["addr:unit"] || "", undefined, { numeric: true }));
  const shown = rows.slice(0, 12);
  const [lon, lat] = shown[0].geometry.coordinates;
  const body = shown.map((f) => {
    const p = f.properties;
    const line1 = [p["addr:housenumber"], p["addr:street"]].filter(Boolean).join(" ");
    const unit = p["addr:unit"] ? `, ${p["addr:unit"]}` : "";
    const line2 = [p["addr:city"], [p["addr:state"], p["addr:postcode"]].filter(Boolean).join(" ")].filter(Boolean).join(", ");
    const pairs = TAG_ORDER.filter((t) => p[t]).map((t) => `${t}=${p[t]}`);
    const tags = pairs.map(esc).join("<br>");
    const copy = `<button type="button" class="copy" title="Copy tags" aria-label="Copy tags"
      data-tags="${esc(pairs.join("\n"))}">${COPY_ICON}${DONE_ICON}</button>`;
    return `<div class="addr"><h3>${esc(line1)}${esc(unit)}</h3><div class="sub">${esc(line2)}</div>
      <div class="tagbox"><p class="tags">${tags}</p>${copy}</div></div>`;
  }).join("");
  const more = rows.length > shown.length ? `<p class="sub">and ${rows.length - shown.length} more here</p>` : "";
  const thin = map.getZoom() < FULL_ZOOM ? `<p class="sub">Points are thinned below zoom ${FULL_ZOOM}; zoom in for all of them.</p>` : "";
  const osm = `https://www.openstreetmap.org/#map=19/${lat.toFixed(6)}/${lon.toFixed(6)}`;
  return `<div class="pop">${body}${more}${thin}<p class="sub"><a href="${osm}" target="_blank" rel="noopener">Open this spot on OpenStreetMap</a></p></div>`;
}

function countyHtml(p) {
  if (!p) return "";
  const nadShare = pct(p.nad, p.points);
  const list = p.sources.slice(0, 15).map(({ id, points }) => {
    const s = coverage.sources[id] || { kind: "nad", name: id };
    const url = s.kind === "other" ? safeUrl(s.page) : null;
    const name = url ? `<a href="${esc(url)}" target="_blank" rel="noopener">${esc(s.name)}</a>` : esc(s.name);
    const licence = s.kind === "other" ? ` <span class="sub">(${esc(s.licence)})</span>` : "";
    return `<li><span><span class="kind" style="background:${s.kind === "other" ? COLORS.other : COLORS.nad}"></span>${name}${licence}</span><span>${fmt.format(points)}</span></li>`;
  }).join("");
  const more = p.sources.length > 15 ? `<p class="sub">and ${p.sources.length - 15} more sources</p>` : "";
  return `<div class="pop">
    <h3>${esc(p.name)}, ${esc(STATES[p.state] || p.state)}</h3>
    <div class="sub">${fmt.format(p.points)} address points</div>
    <div class="bar" role="img" aria-label="${nadShare}% from NAD">
      <span style="width:${nadShare}%;background:${COLORS.nad}"></span>
      <span style="width:${100 - nadShare}%;background:${COLORS.other}"></span>
    </div>
    <div class="sub">NAD ${fmt.format(p.nad)} · other sources ${fmt.format(p.other)}</div>
    <ul>${list}</ul>${more}
  </div>`;
}
