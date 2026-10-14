## Using it

### In a browser with MapLibre

The viewer in [site/](site/) is a complete example. The core of it:

```js
const protocol = new pmtiles.Protocol();
maplibregl.addProtocol("pmtiles", protocol.tile);

map.addSource("addresses", {
  type: "vector",
  url: "pmtiles://https://nad.watmildon.org/nad-current.pmtiles",
});
map.addLayer({
  id: "points",
  type: "circle",
  source: "addresses",
  "source-layer": "addresses",
  minzoom: 10,
  paint: { "circle-radius": 2.5 },
});
```

### Cutting out a region

The [pmtiles CLI](https://github.com/protomaps/go-pmtiles) can extract a bounding box over
HTTP without downloading the whole archive:

```sh
pmtiles show https://nad.watmildon.org/nad-current.pmtiles
pmtiles extract https://nad.watmildon.org/nad-current.pmtiles austin.pmtiles --bbox=-97.95,30.10,-97.55,30.55
```

GDAL 3.8 or later reads PMTiles, so the extract can go on to GeoJSON or anything else GDAL
writes. Ask for zoom 14 so you get every point:

```sh
ogr2ogr -f GeoJSON austin.geojson austin.pmtiles addresses -oo ZOOM_LEVEL=14
```

### In QGIS

QGIS 3.32 or later opens a remote PMTiles URL as a vector tile layer. Add a new Vector Tiles
connection, choose PMTiles as the source type, and paste the `nad-current.pmtiles` URL.

### In JOSM

The JOSM `pmtiles` plugin reads this kind of archive, and the MapWithAI plugin uses it to
offer address points as a conflation source. Only zoom 14 should be read for editing.