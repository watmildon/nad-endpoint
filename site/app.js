// NAD+ viewer: the published PMTiles for zoom 10+ and a county coverage overlay below.
// ?data=<base url> points the page at another copy of the files (e.g. a local test server).

const params = new URLSearchParams(location.search);
const DATA = (params.get("data") || "https://nad.watmildon.org").replace(/\/$/, "");
const TILES = `${DATA}/nad-current.pmtiles`;
const COVERAGE = `${DATA}/nad-current-coverage.geojson`;
const SIDECAR = `${DATA}/nad-current.json`;
const OSM_COUNTS = `${DATA}/osm-counts-current.json`;
const OSM_HISTORY = `${DATA}/osm-counts-history.json`;

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

// Census state codes, the first two digits of a county GEOID.
const STATE_FIPS = {
  AL: "01", AK: "02", AZ: "04", AR: "05", CA: "06", CO: "08", CT: "09", DE: "10", DC: "11",
  FL: "12", GA: "13", HI: "15", ID: "16", IL: "17", IN: "18", IA: "19", KS: "20", KY: "21",
  LA: "22", ME: "23", MD: "24", MA: "25", MI: "26", MN: "27", MS: "28", MO: "29", MT: "30",
  NE: "31", NV: "32", NH: "33", NJ: "34", NM: "35", NY: "36", NC: "37", ND: "38", OH: "39",
  OK: "40", OR: "41", PA: "42", RI: "44", SC: "45", SD: "46", TN: "47", TX: "48", UT: "49",
  VT: "50", VA: "51", WA: "53", WV: "54", WI: "55", WY: "56", AS: "60", GU: "66", MP: "69",
  PR: "72", VI: "78",
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

// OSM address counts per county, rebuilt weekly apart from NAD releases. Fetched straight
// away, not on map load; the viewer works without them.
const osm = { counts: null, asOf: null };
const osmLoaded = fetch(OSM_COUNTS)
  .then((res) => (res.ok ? res.json() : null))
  .then((data) => {
    if (!data) return;
    osm.counts = data.counties;
    osm.asOf = (data.newest_edit || data.published || "").slice(0, 10);
    $("osm-note").textContent = `OSM address counts from OpenStreetMap US Layercake, as of ${osm.asOf}, `
      + "and monthly history from ohsome (HeiGIT); © OpenStreetMap contributors.";
    $("osm-note").hidden = false;
  })
  .catch(() => {});

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
  for (const f of data.features) {
    const b = emptyBounds();
    eachCoordinate(f.geometry, ([x, y]) => extend(b, x, y));
    coverage.byGeoid.set(f.properties.geoid, { ...f.properties, bounds: lngLatBounds(b) });
  }

  await osmLoaded;
  renderStates(data);
  renderSources(data.release, coverage.sources);
  $("coverage-status").textContent = `${fmt.format(data.features.length)} counties hold points.`;
}

function renderStates(data) {
  const states = new Map();
  for (const f of data.features) {
    const p = f.properties;
    const s = states.get(p.state) || { points: 0, ...emptyBounds() };
    s.points += p.points;
    eachCoordinate(f.geometry, ([x, y]) => extend(s, x, y));
    states.set(p.state, s);
  }

  // Every state and territory is listed, since OSM has addresses where NAD+ has none. A row
  // opens its OSM history below it, and flies to the state when it has points: the coverage
  // polygons are what give its bounds.
  const tbody = $("states").querySelector("tbody");
  tbody.replaceChildren();
  const codes = Object.keys(STATES).sort((a, b) => STATES[a].localeCompare(STATES[b]));
  for (const code of codes) {
    const s = states.get(code);
    const fips = STATE_FIPS[code];
    const total = osmStateTotal(fips);
    const tr = document.createElement("tr");
    tr.className = "go";
    tr.tabIndex = 0;
    tr.setAttribute("aria-expanded", "false");
    tr.innerHTML = `<td>${esc(STATES[code])}</td>
      <td class="num">${s ? fmt.format(s.points) : "–"}</td>
      <td class="num">${total === undefined ? "–" : fmt.format(total)}</td>`;
    const go = () => {
      if (toggleStateTrend(tr, fips) && s) flyToState(s);
    };
    tr.addEventListener("click", go);
    tr.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); go(); } });
    tbody.append(tr);
  }
  $("states").hidden = false;
}

// OSM counts cover every county in the state, not only those with points.
function osmStateTotal(fips) {
  if (!osm.counts) return undefined;
  let total = 0;
  for (const [geoid, n] of Object.entries(osm.counts)) if (geoid.startsWith(fips)) total += n;
  return total;
}

// One state's history is open at a time, in a row under the state's own. Returns whether
// the row was opened (rather than closed).
function toggleStateTrend(tr, fips) {
  const open = tr.nextElementSibling?.classList.contains("detail");
  for (const row of tr.parentElement.querySelectorAll("tr.detail")) row.remove();
  for (const row of tr.parentElement.querySelectorAll("tr[aria-expanded=true]")) row.setAttribute("aria-expanded", "false");
  if (open) return false;
  const detail = document.createElement("tr");
  detail.className = "detail";
  detail.innerHTML = `<td colspan="3"><div class="trend-title">Addresses in OpenStreetMap</div>
    <div class="trend"></div><p class="trend-note"></p></td>`;
  tr.after(detail);
  tr.setAttribute("aria-expanded", "true");
  drawTrend(detail.querySelector(".trend"), (h) => h.states.get(fips), osmStateTotal(fips));
  return true;
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

// Bounds kept separately for each hemisphere so an area across the antimeridian (Alaska's
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

function lngLatBounds(b) {
  const hasWest = b.west[0] <= b.west[1];
  const hasEast = b.east[0] <= b.east[1];
  let w, e;
  if (hasWest && hasEast && b.west[1] < -100 && b.east[0] > 100) {
    [w, e] = [b.east[0] - 360, b.west[1]];
  } else {
    w = Math.min(hasWest ? b.west[0] : Infinity, hasEast ? b.east[0] : Infinity);
    e = Math.max(hasWest ? b.west[1] : -Infinity, hasEast ? b.east[1] : -Infinity);
  }
  return [[w, b.south], [e, b.north]];
}

function flyToState(s) {
  if (narrow) setCollapsed(true);
  map.fitBounds(lngLatBounds(s), { padding: sidePadding(), maxZoom: 11 });
}

// Small counties come in past zoom 10, where the address points start.
function flyToCounty(geoid) {
  const county = coverage.byGeoid.get(geoid);
  if (!county) return;
  if (narrow) setCollapsed(true);
  map.fitBounds(county.bounds, { padding: sidePadding(), maxZoom: 15 });
}

// ---- OSM history chart -------------------------------------------------------------------

// Monthly counts from ohsome up to July 2026, fetched on first use since the file is large.
// The weekly Layercake count is drawn as the latest point after them.
let historyLoad = null;

function loadHistory() {
  historyLoad ||= fetch(OSM_HISTORY)
    .then((res) => {
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return res.json();
    })
    .then((data) => {
      const states = new Map();
      for (const [geoid, values] of Object.entries(data.counties)) {
        const fips = geoid.slice(0, 2);
        const sum = states.get(fips) || new Array(values.length).fill(0);
        values.forEach((v, i) => { sum[i] += v; });
        states.set(fips, sum);
      }
      return { dates: data.dates, counties: data.counties, states };
    })
    .catch((err) => {
      historyLoad = null;  // let a later chart try again
      throw err;
    });
  return historyLoad;
}

const TREND_KEY = "nad-trend-open";
let trendOpen = true;
try {
  trendOpen = localStorage.getItem(TREND_KEY) !== "0";
} catch {
  // No storage (private window, blocked site data): keep the default for this visit.
}

function setTrendOpen(open) {
  trendOpen = open;
  try {
    localStorage.setItem(TREND_KEY, open ? "1" : "0");
  } catch {
    // As above; the choice still holds until the page is reloaded.
  }
}

const monthFmt = new Intl.DateTimeFormat("en-US", { month: "short", year: "numeric", timeZone: "UTC" });
const dayFmt = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
const compact = new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 });

async function drawTrend(el, pick, current) {
  const note = el.nextElementSibling;
  el.textContent = "Loading history…";
  let history;
  try {
    history = await loadHistory();
  } catch {
    el.textContent = "The history is not available right now.";
    return;
  }
  const values = pick(history) || history.dates.map(() => 0);
  const points = history.dates.map((d, i) => ({ t: Date.parse(d), v: values[i], label: monthFmt.format(Date.parse(d)) }));
  const last = history.dates[history.dates.length - 1];
  if (current !== undefined && osm.asOf > last) {
    points.push({ t: Date.parse(osm.asOf), v: current, label: `${dayFmt.format(Date.parse(osm.asOf))} (weekly count)` });
  }
  el.textContent = "";
  renderTrend(el, points);
  if (note) {
    note.textContent = `Monthly to ${monthFmt.format(Date.parse(last))} from ohsome; the last point is the current weekly count.`;
  }
}

// Rounds up to 1, 2 or 5 times a power of ten, so the top gridline is a clean number.
function niceMax(v) {
  if (v <= 0) return 10;
  const p = 10 ** Math.floor(Math.log10(v));
  return [1, 2, 5, 10].map((m) => m * p).find((m) => m >= v);
}

function renderTrend(el, points) {
  const W = Math.max(200, el.clientWidth || 260);
  const H = 120;
  const m = { top: 8, right: 8, bottom: 18, left: 34 };
  const t0 = points[0].t;
  const t1 = points[points.length - 1].t;
  const top = niceMax(Math.max(...points.map((p) => p.v)));
  const x = (t) => m.left + ((t - t0) / (t1 - t0)) * (W - m.left - m.right);
  const y = (v) => H - m.bottom - (v / top) * (H - m.top - m.bottom);
  const line = points.map((p, i) => `${i ? "L" : "M"}${x(p.t).toFixed(1)},${y(p.v).toFixed(1)}`).join("");
  const area = `${line}L${x(t1).toFixed(1)},${y(0)}L${x(t0).toFixed(1)},${y(0)}Z`;

  const grid = [0, top / 2, top].map((v) => `<line class="grid" x1="${m.left}" x2="${W - m.right}"
    y1="${y(v)}" y2="${y(v)}"/><text class="axis" x="${m.left - 5}" y="${y(v) + 3.5}" text-anchor="end">${compact.format(v)}</text>`).join("");
  const firstYear = new Date(t0).getUTCFullYear();
  const lastYear = new Date(t1).getUTCFullYear();
  const step = Math.ceil((lastYear - firstYear) / 3);
  const years = [];
  for (let yr = firstYear; yr <= lastYear; yr += step) years.push(yr);
  const ticks = years.map((yr) => {
    const tx = x(Date.UTC(yr, 0, 1));
    const anchor = tx > W - m.right - 14 ? "end" : "middle";
    return `<text class="axis" x="${tx.toFixed(1)}" y="${H - 4}" text-anchor="${anchor}">${yr}</text>`;
  }).join("");
  const end = points[points.length - 1];
  const first = points.find((p) => p.v > 0);
  const summary = first
    ? `OpenStreetMap addresses over time: ${fmt.format(first.v)} in ${first.label}, ${fmt.format(end.v)} by ${end.label}.`
    : "OpenStreetMap addresses over time: none recorded.";

  el.innerHTML = `<svg width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" tabindex="0"
      aria-label="${esc(summary)} Use the arrow keys to read each month.">
    ${grid}${ticks}
    <path class="area" d="${area}"/>
    <path class="line" d="${line}"/>
    <line class="cross" y1="${m.top}" y2="${H - m.bottom}" visibility="hidden"/>
    <circle class="end" cx="${x(end.t).toFixed(1)}" cy="${y(end.v).toFixed(1)}" r="4"/>
    <circle class="focus" r="4" visibility="hidden"/>
    <rect class="hit" x="${m.left}" y="0" width="${W - m.left - m.right}" height="${H}"/>
  </svg><div class="tip" hidden aria-live="polite"><strong></strong><span></span></div>`;

  const svg = el.querySelector("svg");
  const cross = svg.querySelector(".cross");
  const focus = svg.querySelector(".focus");
  const tip = el.querySelector(".tip");
  let at = points.length - 1;

  const show = (i) => {
    at = Math.max(0, Math.min(points.length - 1, i));
    const p = points[at];
    const px = x(p.t);
    const py = y(p.v);
    cross.setAttribute("x1", px);
    cross.setAttribute("x2", px);
    focus.setAttribute("cx", px);
    focus.setAttribute("cy", py);
    cross.setAttribute("visibility", "visible");
    focus.setAttribute("visibility", "visible");
    tip.querySelector("strong").textContent = fmt.format(p.v);
    tip.querySelector("span").textContent = p.label;
    tip.hidden = false;
    // Keep the tip inside the chart: centred over the point, clamped at both edges, and
    // below the point when there is no room above it.
    const half = tip.offsetWidth / 2;
    tip.style.left = `${Math.max(half, Math.min(W - half, px))}px`;
    tip.style.top = `${py - 10 >= tip.offsetHeight ? py - 10 : py + 10 + tip.offsetHeight}px`;
  };
  const hide = () => {
    cross.setAttribute("visibility", "hidden");
    focus.setAttribute("visibility", "hidden");
    tip.hidden = true;
  };
  const nearest = (clientX) => {
    const box = svg.getBoundingClientRect();
    const t = t0 + ((clientX - box.left - m.left) / (W - m.left - m.right)) * (t1 - t0);
    let best = 0;
    for (let i = 1; i < points.length; i++) {
      if (Math.abs(points[i].t - t) < Math.abs(points[best].t - t)) best = i;
    }
    return best;
  };
  svg.addEventListener("pointermove", (e) => show(nearest(e.clientX)));
  svg.addEventListener("pointerleave", hide);
  svg.addEventListener("focus", () => show(at));
  svg.addEventListener("blur", hide);
  svg.addEventListener("keydown", (e) => {
    const moves = { ArrowLeft: -1, ArrowRight: 1, PageUp: -12, PageDown: 12 };
    if (e.key in moves) show(at + moves[e.key]);
    else if (e.key === "Home") show(0);
    else if (e.key === "End") show(points.length - 1);
    else return;
    e.preventDefault();
  });
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
  // The history in a county popup opens or stays shut as the reader last left it, in any
  // popup. It is drawn the first time it is open, since a shut <details> has no width.
  const fold = p.getElement().querySelector(".trend-fold");
  if (fold) {
    const chart = fold.querySelector(".trend");
    const draw = () => {
      if (!fold.open || chart.dataset.drawn) return;
      chart.dataset.drawn = "1";
      const geoid = chart.dataset.geoid;
      drawTrend(chart, (h) => h.counties[geoid], osm.counts?.[geoid]);
    };
    fold.addEventListener("toggle", () => {
      setTrendOpen(fold.open);
      draw();
    });
    draw();
  }
  p.getElement().addEventListener("click", (e) => {
    const copy = e.target.closest("button.copy");
    if (copy) copyTags(copy);
    const zoom = e.target.closest("button.zoom");
    if (zoom) {
      p.remove();
      flyToCounty(zoom.dataset.geoid);
    }
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

const ZOOM_ICON = `<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
  <circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" stroke-width="1.4"/>
  <path d="M10.3 10.3L14 14M7 5v4M5 7h4" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
</svg>`;

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

// OSM counts elements with addr:housenumber, a different measure from the points above, so
// the two are shown apart and never compared.
function osmHtml(p) {
  const n = osm.counts?.[p.geoid];
  if (n === undefined) return "";
  return `<div class="osm">
    <div class="row"><span>Addresses in OpenStreetMap</span><span>${fmt.format(n)}</span></div>
    <div class="sub">OSM as of ${esc(osm.asOf)}</div>
    <details class="trend-fold"${trendOpen ? " open" : ""}>
      <summary>Over time</summary>
      <div class="trend" data-geoid="${esc(p.geoid)}"></div><p class="trend-note"></p>
    </details>
  </div>`;
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
    <div class="sub">NAD ${fmt.format(p.nad)} · non-NAD ${fmt.format(p.other)}</div>
    <ul>${list}</ul>${more}
    ${osmHtml(p)}
    <button type="button" class="zoom" data-geoid="${esc(p.geoid)}">${ZOOM_ICON}Zoom to county</button>
  </div>`;
}
