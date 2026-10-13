"""Reviewed facts about ZIP codes, kept in zip_facts.json.

Each ZIP has a state and a kind:
  single    every address in it has the postal city `city`
  multiple  more than one postal city (`cities`), so the ZIP alone can't name one
  invalid   not a real ZIP (a source's placeholder), so nothing may be inferred from it
Each entry's note says what the fact rests on.
"""

import json
import re
from pathlib import Path
from typing import NamedTuple

ZIP_FACTS_FILE = Path(__file__).with_name("zip_facts.json")
KINDS = ("single", "multiple", "invalid")


class ZipFact(NamedTuple):
    zip: str
    state: str
    kind: str
    city: str | None = None
    cities: tuple[str, ...] = ()
    note: str | None = None


def load_zip_facts(path: Path = ZIP_FACTS_FILE) -> list[ZipFact]:
    """The facts in the ZIP file; raises on a malformed entry."""
    with open(path, encoding="utf-8") as f:
        facts = [ZipFact(z, e["state"], e["kind"], e.get("city"), tuple(e.get("cities", ())),
                         e.get("note"))
                 for z, e in json.load(f).items()]
    for fact in facts:
        problem = (
            "not a 5-digit ZIP" if not re.fullmatch(r"\d{5}", fact.zip)
            else "unknown kind" if fact.kind not in KINDS
            else "a single ZIP needs a city" if fact.kind == "single" and not fact.city
            else "a multiple ZIP needs two or more cities" if fact.kind == "multiple"
            and len(fact.cities) < 2
            else None)
        if problem:
            raise ValueError(f"{path.name}: {fact.zip}: {problem}")
    return facts


def single_city_zips(facts) -> list[tuple[str, str, str]]:
    """(state, zip, city) for every ZIP known to have one postal city."""
    return [(f.state, f.zip, f.city) for f in facts if f.kind == "single"]
