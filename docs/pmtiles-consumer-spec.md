# Consuming the NAD address tileset

This describes the PMTiles file produced by this pipeline's `export` stage so that a client
(a JOSM plugin or similar) can read it without reference to the pipeline code. Everything a
client may rely on is stated here; anything not stated may change between releases.

## 1. The file

- One PMTiles (version 3) archive per NAD release, named `nad-<release>.pmtiles`, for
  example `nad-r24.pmtiles`. `<release>` is USDOT's release number.
- A sidecar `nad-<release>.json` next to it (section 7).
- Hosted on object storage that supports HTTP range requests (`Range` and `Content-Range`)
  and CORS `GET`/`HEAD`. Clients must read by range; the archive is several gigabytes and
  must never be downloaded whole.
- The URL of the current release is `.../nad-current.pmtiles`, which the publisher repoints
  at each release. Release-numbered URLs stay available after a new release so that a client
  that noticed the release number can keep reading the same data.

## 2. Tile layout

| Field | Value |
|---|---|
| Tile type | Mapbox Vector Tile (MVT), protobuf |
| Tile compression | gzip (see the PMTiles header `tile_compression`; do not assume, read it) |
| Projection | Web Mercator tile grid, XYZ scheme (`y` counts from the north) |
| Minimum zoom | 10 |
| Maximum zoom | 14 |
| Layer | one layer, named `addresses` |
| Geometry | points only |
| Extent | 4096 per tile (MVT default) |

Zoom 14 is **complete**: every published point is present in exactly one zoom-14 tile. The
tiles are built with no edge buffer and no duplication at tile seams, so the sum of features
over all zoom-14 tiles equals the published point count. A point that falls on a tile's
edge has a tile coordinate of 0 or exactly `extent` (4096); it is still a real point that
appears nowhere else, so clients must keep features whose coordinates lie in the closed
range `[0, extent]` and must not discard them as buffer copies.

Zooms 10–13 are thinned for display and must not be used for editing or counting. A client
that wants the data for an area must enumerate the zoom-14 tiles covering the area's
bounding box, fetch each, and read the `addresses` layer.

Read the minimum and maximum zoom from the PMTiles header rather than hard-coding them; a
later release may move the complete zoom to 15 if dense tiles grow too large.

Dense urban zoom-14 tiles can hold tens of thousands of points and a few megabytes
compressed. Clients should fetch tiles concurrently and should not assume a per-tile limit.

## 3. Features

Each feature is one address point. The MVT `id` field is not set on any feature; a decoder
that reports a default id of 0 is reporting its own default. Identity across releases is not
provided in this tileset (section 8).

### Properties

All property values are strings. A property is **absent** when the pipeline has no value;
clients must treat absent and empty as "no value" and must not write an empty tag.

| Property | Always present | Content |
|---|---|---|
| `addr:housenumber` | yes | House number as written in the source, with any prefix or suffix: `114`, `102 C`, `607 1/2`, `89-02`, `W235 A` |
| `addr:street` | yes | Full street name with directionals and type spelled out: `East Saint Clair Street`, `County Road 123`, `Avenue N`. Route designators that vary by state are left as written: `FM 1960`, `SR 125`, `US 50` |
| `addr:unit` | no | Sub-address as delivered, lightly normalised: `2`, `Apt A`, `Unit 108`, `Bldg B Ste 3`, `Rear`, `12-16`. Designators are not stripped |
| `addr:city` | no | Postal city where the source gives one; otherwise the municipality or community; otherwise a city derived from the point's location (section 5) |
| `addr:state` | yes | Two-letter USPS code |
| `addr:postcode` | no | Five-digit ZIP code; never ZIP+4 |

Property names are exactly the OSM keys above, so a client may copy them onto a node
unchanged. There are no other properties; a client that finds one it does not know should
ignore it rather than copy it.

### Semantics a client should know

- Several features may share a position: units of one building, or one building with and
  without units. The pipeline keeps all of them. A point with no `addr:unit` alongside
  points with units is the building-level address, not a duplicate.
- The same house number and street may occur twice more than 100 m apart within one city.
  Both are published; the pipeline cannot tell which is right.
- `addr:street` is the pipeline's expansion of the source's components. It is not checked
  against OSM road names, and OSM may lack or carry a directional that the address has.
  Treat a directional-only difference as agreement, not conflict.
- `addr:city` is the postal city by preference, matching OSM's `addr:city` convention,
  but see section 5.
- Points are placed where the source placed them: on a rooftop, at an entrance, at a parcel
  centroid, or at an unknown placement. The tileset does not say which.

## 4. What is not in the tileset

Rows the pipeline dropped are absent: addresses with no house number or street, placeholder
street names, inactive lifecycle (proposed, retired and similar), mileposts, block ranges,
and duplicates (same state, county, number, street and unit within 100 m; the best-placed
and most recently updated copy stays).

Audit data (the NAD record UUID, source agency, placement, update date, and the rule flags
that say what the pipeline changed or doubted) is deliberately not in this tileset, because
some consumers copy every property to OSM. It is available in the pipeline's Parquet
output and may be published as a separate tileset with the same tile layout later.

## 4a. Coverage

The tileset covers what the NAD release covers, which is not the whole country. In r24
there are no points at all for Hawaii, Michigan, Mississippi, Nevada, New Hampshire, Puerto
Rico, Guam, American Samoa or the Northern Mariana Islands, and several covered states are
partial (Florida has about 43K points, Georgia about 205K, California and Pennsylvania a
fraction of their addresses). The US Virgin Islands are present in the source but almost
entirely with a "Proposed" lifecycle, which the pipeline excludes, so only a handful of
points remain. Coverage changes with each release; the sidecar's `points` count is the
only summary the tileset itself gives.

## 5. Derived values

Some `addr:city` and `addr:postcode` values are derived rather than delivered:

- City from the state's own 911 dataset when NAD had none (Kentucky, Indiana).
- City from the Census place or New England town polygon the point falls in.
- Postcode from the Census ZIP polygon the point falls in.

The tileset does not mark which values are derived (that is in the audit data). A client
that wants to be cautious with `addr:city` or `addr:postcode` on points where other nearby
points disagree should prefer the majority.

## 6. Reading the archive

A minimal reader needs:

1. `GET` the first 16 KiB by range; parse the 127-byte PMTiles v3 header and the root
   directory that follows it (the header gives offset and length).
2. For each tile `(z, x, y)` at the maximum zoom covering the request area, compute the
   Hilbert tile id, look it up in the root directory, following into a leaf directory when
   the entry points to one, and read the tile bytes by range.
3. Decompress per the header's `tile_compression`, decode the MVT, take layer `addresses`,
   convert each point from tile coordinates to WGS84.

Directories are compressed with the header's `internal_compression`. The JOSM `pmtiles`
plugin's `PMTiles` class implements all of this and the MapWithAI plugin reads this kind of
file through it; a new consumer can use the same library.

Cache the header and root directory per URL for the session. Tiles may be cached by URL,
tile id and the header's `etag`, if the host returns one; a republish of the same release
number is a bug, not something to design for.

## 7. The sidecar

`nad-<release>.json` is small and may be fetched whole:

```json
{
  "release": "r24",
  "built": "2026-10-06",
  "points": 98418873,
  "layer": "addresses",
  "min_zoom": 10,
  "max_zoom": 14,
  "tags": ["addr:housenumber", "addr:street", "addr:unit", "addr:city", "addr:state", "addr:postcode"],
  "file": "nad-r24.pmtiles",
  "bytes": 0
}
```

`tags` lists the properties the tileset carries. A client can use it to detect a release
that adds a property. `points` is the number of features at the maximum zoom.

## 8. Versioning and stability

- A new NAD release produces a new file. Releases are quarterly. Point positions, numbers
  and streets can all change between releases, and there is no per-feature id to follow a
  point across them.
- Within this document's lifetime: the layer name, the property names in section 3, the
  rule that the maximum zoom is complete, and the sidecar fields above will not change
  without a new major version of this spec.
- Things that may change with notice in the sidecar: zoom range, the addition of
  properties, a second audit tileset.

## 9. Mapping to an OpenAddresses-style conform

For a client that models sources as an OpenAddresses "conform":

| conform field | property |
|---|---|
| `number` | `addr:housenumber` |
| `street` | `addr:street` (already expanded; do not run expansion again) |
| `unit` | `addr:unit` |
| `city` | `addr:city` |
| `region` | `addr:state` |
| `postcode` | `addr:postcode` |
| `district` | not provided |

## 10. Licence

The source data is in the public domain (US Department of Transportation, National Address
Database). Values derived from Census boundaries are public domain. Values filled from state
datasets come from sources published without reuse conditions; the pipeline records the
terms per source. A client need not add attribution to OSM tags, but should let mappers
record the source in the changeset.
