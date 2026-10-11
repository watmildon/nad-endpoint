import io
import json
import urllib.error

import pytest

from nad_pipeline import config, osmhistory, refdata

from test_backfill_dedup import geojson, square

DATES = ["2020-01-01", "2020-02-01"]


def answer(features, dates):
    """ohsome's answer, counting 10 per month plus the GEOID's last digit."""
    return {"groupByResult": [
        {"groupByObject": f["properties"]["id"],
         "result": [{"timestamp": f"{d}T00:00:00Z",
                     "value": float(10 * DATES.index(d) + int(f["properties"]["id"][-1]))}
                    for d in dates]}
        for f in features
    ]}


def shapes(*geoids, vertices=5):
    return [(g, {"type": "Point", "coordinates": [0, 0]}, vertices) for g in geoids]


def too_big():
    return urllib.error.HTTPError(osmhistory.URL, 413, "Payload Too Large", {}, io.BytesIO())


def quiet(message):
    pass


def test_batches_follow_the_address_and_vertex_budgets():
    current = {"01001": 50, "01003": 40, "01005": 30, "01007": 200}
    groups = list(osmhistory.batches(shapes("01001", "01003", "01005", "01007"), current,
                                     budget=100, max_vertices=1000))
    assert [[g for g, _, _ in b] for b in groups] == [["01001", "01003"], ["01005"], ["01007"]]
    groups = list(osmhistory.batches(shapes("01001", "01003", "01005", vertices=400), {},
                                     budget=100, max_vertices=1000))
    assert [len(b) for b in groups] == [2, 1]


def test_fetch_all_joins_batches_and_caches_each(tmp_path):
    calls = []

    def post(features, dates):
        calls.append([f["properties"]["id"] for f in features])
        return answer(features, dates)

    groups = [shapes("01001", "01003"), shapes("01005")]
    series = osmhistory.fetch_all(groups, DATES, post, tmp_path, quiet)
    assert series == {"dates": DATES,
                      "counties": {"01001": [1, 11], "01003": [3, 13], "01005": [5, 15]}}
    assert calls == [["01001", "01003"], ["01005"]]
    # A second run reads the cache and asks nothing.
    assert osmhistory.fetch_all(groups, DATES, post, tmp_path, quiet) == series
    assert len(calls) == 2


def test_a_batch_too_big_for_the_server_is_split_by_counties(tmp_path):
    calls = []

    def post(features, dates):
        calls.append(len(features))
        if len(features) > 1:
            raise too_big()
        return answer(features, dates)

    series = osmhistory.fetch_all([shapes("01001", "01003", "01005")], DATES, post, tmp_path, quiet)
    assert series["counties"] == {"01001": [1, 11], "01003": [3, 13], "01005": [5, 15]}
    assert calls == [3, 1, 2, 1, 1]
    # A resumed run finds the whole batch cached and does not try it again.
    assert osmhistory.fetch_all([shapes("01001", "01003", "01005")], DATES, post, tmp_path,
                                quiet) == series
    assert len(calls) == 5


def test_a_single_county_too_big_is_split_by_dates(tmp_path):
    calls = []

    def post(features, dates):
        calls.append(dates)
        if len(dates) > 1:
            raise too_big()
        return answer(features, dates)

    series = osmhistory.fetch_all([shapes("01001")], DATES, post, tmp_path, quiet)
    assert series["counties"] == {"01001": [1, 11]}
    assert calls == [DATES, DATES[:1], DATES[1:]]


@pytest.fixture
def waits(monkeypatch):
    slept = []
    monkeypatch.setattr(osmhistory.time, "sleep", slept.append)
    return slept


def busy():
    return urllib.error.HTTPError(osmhistory.URL, 503, "Service Unavailable", {}, io.BytesIO())


@pytest.mark.parametrize("error", [TimeoutError("timed out"), busy()])
def test_a_busy_server_is_waited_out_not_split(tmp_path, waits, error):
    calls = []

    def post(features, dates):
        calls.append(len(features))
        if len(calls) < 3:
            raise error
        return answer(features, dates)

    series = osmhistory.fetch_all([shapes("01001", "01003")], DATES, post, tmp_path, quiet)
    assert sorted(series["counties"]) == ["01001", "01003"]
    assert calls == [2, 2, 2]
    assert waits == [osmhistory.WAIT, 2 * osmhistory.WAIT]


def test_a_server_busy_past_the_retries_stops_the_run(tmp_path, waits):
    def post(features, dates):
        raise TimeoutError("timed out")

    with pytest.raises(TimeoutError):
        osmhistory.fetch_all([shapes("01001", "01003")], DATES, post, tmp_path, quiet)
    assert len(waits) == osmhistory.RETRIES - 1


def test_a_single_county_and_date_too_big_fails(tmp_path):
    def post(features, dates):
        raise too_big()

    with pytest.raises(urllib.error.HTTPError):
        osmhistory.fetch_all([shapes("01001")], DATES[:1], post, tmp_path, quiet)


def test_an_answer_for_other_counties_fails(tmp_path):
    def post(features, dates):
        return answer([{"properties": {"id": "99999"}}], dates)

    with pytest.raises(ValueError, match="99999"):
        osmhistory.fetch_all([shapes("01001")], DATES, post, tmp_path, quiet)


def test_osm_history_writes_the_series(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(osmhistory, "DATES", DATES)
    counties = geojson(tmp_path / "counties.geojson", [
        square(-87, 40, -86, 41, GEOID="18001"),
        square(-86, 40, -85, 41, GEOID="18003"),
    ])
    monkeypatch.setattr(refdata, "download_boundaries", lambda ref, kinds: None)
    monkeypatch.setattr(refdata, "boundary_file", lambda ref, kind: counties)
    counts = tmp_path / "data" / "osm-counts"
    counts.mkdir(parents=True)
    (counts / "osm-counts-2026-10-04.json").write_text(
        json.dumps({"counties": {"18001": 5, "18003": 7}}), encoding="utf-8")
    sent = []

    def post(features, dates):
        sent.append(features)
        return answer(features, dates)

    out = osmhistory.osm_history(post=post, log=quiet)
    assert out == counts / "osm-counts-history.json"
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["dates"] == DATES
    assert data["counties"] == {"18001": [1, 11], "18003": [3, 13]}
    assert data["filter"] == "addr:housenumber=*"
    assert data["attribution"] == "© OpenStreetMap contributors"
    assert [f["geometry"]["type"] for f in sent[0]] == ["Polygon", "Polygon"]


def test_osm_history_needs_current_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    with pytest.raises(FileNotFoundError, match="nad osm-counts"):
        osmhistory.latest_counts()


def test_dates_are_monthly_to_july_2026():
    assert osmhistory.DATES[:2] == ["2008-01-01", "2008-02-01"]
    assert osmhistory.DATES[-1] == "2026-07-01" and len(osmhistory.DATES) == 223
