import json

import pytest

from nad_pipeline.rules.zips import KINDS, load_zip_facts, single_city_zips


def test_zip_facts_file_is_consistent():
    facts = load_zip_facts()
    assert facts
    for fact in facts:
        assert len(fact.state) == 2 and fact.kind in KINDS and fact.note
        if fact.kind == "single":
            assert fact.city and not fact.cities
        if fact.kind == "invalid":
            assert not fact.city and not fact.cities
    assert all(len(row) == 3 for row in single_city_zips(facts))


@pytest.mark.parametrize("entry, problem", [
    ({"4033": {"state": "KY", "kind": "single", "city": "Irvine"}}, "not a 5-digit ZIP"),
    ({"40336": {"state": "KY", "kind": "only", "city": "Irvine"}}, "unknown kind"),
    ({"40336": {"state": "KY", "kind": "single"}}, "needs a city"),
    ({"75156": {"state": "TX", "kind": "multiple", "cities": ["Mabank"]}}, "two or more"),
])
def test_malformed_zip_facts_are_rejected(tmp_path, entry, problem):
    path = tmp_path / "zip_facts.json"
    path.write_text(json.dumps(entry))
    with pytest.raises(ValueError, match=problem):
        load_zip_facts(path)


def test_single_city_zips_skips_other_kinds(tmp_path):
    path = tmp_path / "zip_facts.json"
    path.write_text(json.dumps({
        "40336": {"state": "KY", "kind": "single", "city": "Irvine", "note": "x"},
        "75156": {"state": "TX", "kind": "multiple", "cities": ["Mabank", "Gun Barrel City"]},
        "00130": {"state": "ME", "kind": "invalid"},
    }))
    assert single_city_zips(load_zip_facts(path)) == [("KY", "40336", "Irvine")]
