"""Spot-check address points against OpenStreetMap in small areas.

Compares a source of OSM-tagged address points (for now the Esri NAD layer) with
OSM street names and, where OSM has them, OSM addresses.
"""

import difflib
import json
import math
import urllib.parse
import urllib.request
from collections import Counter, defaultdict

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
ESRI_NAD_LAYER = (
    "https://services6.arcgis.com/Do88DoK2xjTUCXd1/arcgis/rest/services/"
    "USA_NAD_Addresses/FeatureServer/0"
)
USER_AGENT = "nad-pipeline-spotcheck/0.1"

# (south, west, north, east)
AREAS = {
    # OSM has addresses and roads
    "phoenix_az": (33.445, -112.095, 33.475, -112.055),
    "indianapolis_in": (39.765, -86.165, 39.795, -86.125),
    "boston_ma": (42.335, -71.095, 42.355, -71.065),
    "denver_co": (39.725, -104.985, 39.75, -104.95),
    # OSM has roads but few addresses
    "columbus_in": (39.195, -85.935, 39.225, -85.895),
    "altoona_ia": (41.635, -93.485, 41.665, -93.445),
    "stuttgart_ar": (34.485, -91.57, 34.515, -91.53),
    "lubbock_tx": (33.555, -101.9, 33.585, -101.86),
}

STREET_NAME_KEYS = ("name", "alt_name", "official_name", "loc_name", "name_1", "short_name")
DIRECTIONALS = {
    "north", "south", "east", "west", "northeast", "northwest", "southeast", "southwest",
    "n", "s", "e", "w", "ne", "nw", "se", "sw",
}
MATCH_RADIUS_M = 100
CELL = 0.001  # degrees; about 100 m of latitude


def _get_json(url: str, data: dict | None = None) -> dict:
    body = urllib.parse.urlencode(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.load(resp)


def fetch_osm(bbox) -> tuple[list[dict], set[str], set[str]]:
    """Return (addresses, primary street names, alternate street names) inside bbox."""
    s, w, n, e = bbox
    query = f"""
        [out:json][timeout:120];
        (
          nwr["addr:housenumber"]({s},{w},{n},{e});
          way["highway"]["name"]({s},{w},{n},{e});
        );
        out tags center;
    """
    addresses, names, alt_names = [], set(), set()
    for el in _get_json(OVERPASS_URL, {"data": query})["elements"]:
        tags = el.get("tags", {})
        if "highway" in tags and el["type"] == "way":
            for key in STREET_NAME_KEYS:
                for value in tags.get(key, "").split(";"):
                    if value.strip():
                        (names if key == "name" else alt_names).add(value.strip())
        if "addr:housenumber" in tags:
            pos = el.get("center", el)
            addresses.append({
                "lat": pos["lat"], "lon": pos["lon"],
                "housenumber": tags["addr:housenumber"],
                "street": tags.get("addr:street"),
                "city": tags.get("addr:city"),
                "postcode": tags.get("addr:postcode"),
            })
    return addresses, names, alt_names - names


def fetch_esri(bbox, layer: str = ESRI_NAD_LAYER) -> list[dict]:
    s, w, n, e = bbox
    points, offset = [], 0
    while True:
        params = urllib.parse.urlencode({
            "where": "1=1", "geometry": f"{w},{s},{e},{n}",
            "geometryType": "esriGeometryEnvelope", "inSR": 4326, "outSR": 4326,
            "spatialRel": "esriSpatialRelIntersects", "outFields": "*",
            "orderByFields": "OBJECTID", "resultOffset": offset, "f": "geojson",
        })
        features = _get_json(f"{layer}/query?{params}")["features"]
        for f in features:
            p = f["properties"]
            lon, lat = f["geometry"]["coordinates"]
            points.append({
                "lat": lat, "lon": lon,
                "housenumber": p.get("addr_housenumber"), "street": p.get("addr_street"),
                "unit": p.get("addr_unit"), "city": p.get("addr_city"),
                "postcode": p.get("addr_postcode"), "source": p.get("source"),
            })
        if not features:
            return points
        offset += len(features)


def _key(value: str | None) -> str:
    return " ".join((value or "").casefold().split())


def _number_key(value: str | None) -> str:
    return _key(value).replace(" ", "")


def _split_directionals(key: str) -> tuple[str, str, str]:
    """Split a normalised street name into (leading directional, core, trailing directional)."""
    words = key.split()
    pre = words.pop(0) if len(words) > 1 and words[0] in DIRECTIONALS else ""
    post = words.pop() if len(words) > 1 and words[-1] in DIRECTIONALS else ""
    return pre, " ".join(words), post


def differs_only_by_directional(a: str | None, b: str | None) -> bool:
    """True if one name has a directional the other lacks and they are otherwise equal.

    OSM road names often omit directionals that addresses carry, so this is not an error
    on either side. Two different directionals (North Main vs South Main) do not count.
    """
    pre_a, core_a, post_a = _split_directionals(_key(a))
    pre_b, core_b, post_b = _split_directionals(_key(b))
    return (
        core_a == core_b
        and (pre_a, post_a) != (pre_b, post_b)
        and (pre_a == pre_b or not pre_a or not pre_b)
        and (post_a == post_b or not post_a or not post_b)
    )


def _distance_m(a: dict, b: dict) -> float:
    dlat = (a["lat"] - b["lat"]) * 111_320
    dlon = (a["lon"] - b["lon"]) * 111_320 * math.cos(math.radians(a["lat"]))
    return math.hypot(dlat, dlon)


def _cell(p: dict) -> tuple[int, int]:
    return (math.floor(p["lat"] / CELL), math.floor(p["lon"] / CELL))


def compare_streets(points: list[dict], names: set[str], alt_names: set[str]) -> dict:
    """Classify each source addr:street by whether an OSM road in the area carries that name."""
    counts = Counter(p["street"] for p in points if p["street"])
    by_key = defaultdict(set)
    for name in names | alt_names:
        by_key[_key(name)].add(name)
    result = {"exact": 0, "alternate": 0, "case_only": 0, "directional_only": 0, "unmatched": 0}
    unmatched, directional = [], []
    for street, n in counts.items():
        if street in names:
            result["exact"] += n
        elif street in alt_names:
            result["alternate"] += n
        elif _key(street) in by_key:
            result["case_only"] += n
            unmatched.append((n, street, sorted(by_key[_key(street)])[0]))
        elif osm_name := next(
            (o for o in sorted(names | alt_names) if differs_only_by_directional(street, o)), None
        ):
            result["directional_only"] += n
            directional.append((n, street, osm_name))
        else:
            result["unmatched"] += n
            close = difflib.get_close_matches(street, names | alt_names, 1, 0.75)
            unmatched.append((n, street, close[0] if close else None))
    result["no_street"] = sum(1 for p in points if not p["street"])
    result["distinct_streets"] = len(counts)
    result["mismatches"] = sorted(unmatched, key=lambda t: (-t[0], t[1]))
    result["directional_differences"] = sorted(directional, key=lambda t: (-t[0], t[1]))
    return result


def compare_addresses(points: list[dict], osm: list[dict]) -> dict:
    """Match distinct source addresses to OSM addresses with the same number nearby."""
    grid = defaultdict(list)
    for a in osm:
        grid[_cell(a)].append(a)
    seen, matched_osm = set(), set()
    result = Counter()
    street_conflicts, city_diffs, postcode_diffs = Counter(), Counter(), Counter()
    for p in points:
        key = (_number_key(p["housenumber"]), _key(p["street"]))
        if key in seen or not key[0]:
            continue
        seen.add(key)
        cy, cx = _cell(p)
        nearby = [
            a for dy in (-1, 0, 1) for dx in (-1, 0, 1) for a in grid[(cy + dy, cx + dx)]
            if _number_key(a["housenumber"]) == key[0] and _distance_m(p, a) <= MATCH_RADIUS_M
        ]
        same_street = [a for a in nearby if _key(a["street"]) == key[1]]
        if not same_street:
            same_street = [
                a for a in nearby if differs_only_by_directional(p["street"], a["street"])
            ]
            if same_street:
                result["matched_directional_differs"] += 1
        if same_street:
            result["matched"] += 1
            a = min(same_street, key=lambda a: _distance_m(p, a))
            matched_osm.add((_number_key(a["housenumber"]), _key(a["street"])))
            if a["city"] and p["city"] != a["city"]:
                city_diffs[(p["city"], a["city"])] += 1
            if a["postcode"] and p["postcode"] != a["postcode"][:5]:
                postcode_diffs[(p["postcode"], a["postcode"])] += 1
        elif nearby:
            result["street_conflict"] += 1
            a = min(nearby, key=lambda a: _distance_m(p, a))
            street_conflicts[(p["street"], a["street"])] += 1
        else:
            result["not_in_osm"] += 1
    osm_keys = {(_number_key(a["housenumber"]), _key(a["street"])) for a in osm}
    return {
        "source_distinct": len(seen),
        "osm_distinct": len(osm_keys),
        **result,
        "osm_only": len(osm_keys - matched_osm),
        "street_conflicts": street_conflicts.most_common(),
        "city_diffs": city_diffs.most_common(),
        "postcode_diffs": postcode_diffs.most_common(),
    }


def spotcheck(bbox, fetch_source=fetch_esri) -> dict:
    points = fetch_source(bbox)
    osm_addresses, names, alt_names = fetch_osm(bbox)
    return {
        "bbox": bbox,
        "source_points": len(points),
        "source_names": Counter(p.get("source") for p in points).most_common(),
        "osm_addresses": len(osm_addresses),
        "osm_street_names": len(names),
        "streets": compare_streets(points, names, alt_names),
        "addresses": compare_addresses(points, osm_addresses),
        "units": Counter(p["unit"] for p in points if p.get("unit")).most_common(40),
        "no_city": sum(1 for p in points if not p["city"]),
    }
