import json
from importlib import resources

from pbg2sed2.classify import lookup, table

ROLES = {"simulator-process", "simulator-step", "steady-state-step", "emitter", "visualization", "declarative-math",
         "stateful-utility", "drawing", "composite", "forward-translator", "coupled-model"}


def test_every_entry_has_a_known_role_and_a_sed2_note():
    for e in table():
        assert e["role"] in ROLES, e
        assert e.get("sed2"), e
        assert e.get("names") or e.get("pattern"), e


def test_names_are_unique_per_kind():
    seen = {}
    for e in table():
        for n in e.get("names", []):
            key = (n, e.get("kind", "any"))
            assert key not in seen, (n, e)
            seen[key] = e


def test_lookup_by_name_and_pattern():
    assert lookup("TelluriumUTCStep", "step")["role"] == "simulator-step"
    assert lookup("TelluriumUTCStep", "process") is None  # kind matters
    assert lookup("SedOdeSimulation", "step")["role"] == "forward-translator"
    assert lookup("SpeciesTimeSeriesPlots", "step")["role"] == "visualization"
    assert lookup("Whatever", "process") is None


def test_the_file_is_ascii_json():
    text = resources.files("pbg2sed2").joinpath("known_classes.json").read_text(encoding="ascii")
    json.loads(text)
