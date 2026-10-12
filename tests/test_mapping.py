import json

import pytest

from conftest import need

from pbg2sed2.classify import classify
from pbg2sed2.emit import EXIT_NOT_TRANSLATABLE, EXIT_WRITTEN, write_result
from pbg2sed2.mapping import Options, translate
from pbg2sed2.reader import Document

need("libsbml")
need("antimony")

MODEL = "model m\n  S1 = 10; S2 = 0\n  S1 -> S2; k*S1; k = 0.3\nend\n"


def node(kind, cls, config=None, inputs=None, outputs=None, **extra):
    d = {"_type": kind, "address": f"local:{cls}", "config": config or {}, "inputs": inputs or {}, "outputs": outputs or {}}
    d.update(extra)
    return d


def utc_doc(config=None, extra_nodes=None):
    cfg = {"model": MODEL, "model_format": "antimony", "start_time": 0.0, "end_time": 4.0, "n_points": 5}
    cfg.update(config or {})
    state = {"sim": node("step", "TelluriumUTCStep", cfg, outputs={"time_series": ["t"], "species_trajectories": ["sp"]}),
             "t": [], "sp": {},
             "em": node("step", "RAMEmitter", {"emit": {"time": "list", "sp": "map"}}, inputs={"time": ["t"], "sp": ["sp"]})}
    state.update(extra_nodes or {})
    return Document(source="t", form="composite-file", state=state)


def run(doc, **opts):
    return translate(doc, classify(doc), Options(name="t", **opts))


def test_utc_step_maps_to_explicit_ode():
    r = run(utc_doc())
    assert r.status == "translatable", r.reasons
    s = r.sed2["tasks"]["s"]
    assert s["_type"] == "explicitODESimulation"
    assert s["independentVariableRange"] == {"_type": "numericRange", "start": 0.0, "end": 4.0, "numberOfSteps": 4}
    assert s["outputVariables"] == ["S1", "S2"]
    assert "t.model.sbml" in r.model_files


def test_species_override_becomes_model_change():
    r = run(utc_doc({"species_overrides": {"S1": 7.0}, "parameter_overrides": {"k": 0.5}}))
    assert r.sed2["tasks"]["c"]["setValues"] == {"S1": 7.0, "k": 0.5}
    assert r.sed2["tasks"]["s"]["model"] == "#tasks:c.model"


@pytest.mark.parametrize("cfg,fragment", [
    ({"integrator": "gillespie"}, "stochastic"),
    ({"selections": ["S1"]}, "selections"),
    ({"output_times": [0, 1]}, "output_times"),
    ({"species_units": "amount"}, "amount"),
    ({"species_overrides": {"nope": 1.0}}, "not a floating species"),
    ({"parameter_overrides": {"nope": 1.0}}, "not a global parameter"),
])
def test_unmapped_settings_are_refused_with_the_reason(cfg, fragment):
    r = run(utc_doc(cfg))
    assert r.status == "not-translatable" and r.sed2 is None
    assert fragment in " ".join(r.reasons)


def test_events_are_refused():
    ev = "model m\n  S1 = 1\n  S1 -> ; k*S1; k = 1\n  at (time > 1): S1 = 5\nend\n"
    r = run(utc_doc({"model": ev}))
    assert r.status == "not-translatable" and "events" in r.reasons[0]


def test_compartment_not_one_blocks_species_overrides():
    m = "model m\n  compartment c = 2\n  species S1 in c = 1\n  S1 -> ; k*S1; k = 1\nend\n"
    r = run(utc_doc({"model": m, "species_overrides": {"S1": 3.0}}))
    assert r.status == "not-translatable" and "compartment" in r.reasons[0]


def test_a_part_without_translation_refuses_the_whole_document(tmp_path):
    extra = {"viz": node("step", "SomePlot", inputs={"x": ["t"]})}
    r = run(utc_doc(extra_nodes=extra))
    assert r.status == "not-translatable" and r.sed2 is None and not r.model_files
    assert "SomePlot" in r.reasons[0] and any(e.cls == "SomePlot" for e in r.dropped)
    assert write_result(r, tmp_path / "a.sed2.json", tmp_path / "a.import.json") == EXIT_NOT_TRANSLATABLE
    assert not (tmp_path / "a.sed2.json").exists() and not (tmp_path / "t.model.sbml").exists()
    rep = json.loads((tmp_path / "a.import.json").read_text())
    assert rep["status"] == "not-translatable" and rep["dropped"][0]["class"] == "SomePlot"


def test_a_complete_document_is_written(tmp_path):
    need("libsed2")                                                  # write_result validates with libsed2 and refuses to write without it
    assert write_result(run(utc_doc()), tmp_path / "b.sed2.json", None) == EXIT_WRITTEN
    assert (tmp_path / "b.sed2.json").exists() and (tmp_path / "t.model.sbml").exists()


def test_no_ram_emitter_is_refused():
    d = utc_doc()
    del d.state["em"]
    r = run(d)
    assert r.status == "not-translatable" and "in-memory emitter" in r.reasons[0]


def test_steady_state_step():
    state = {"sim": node("step", "TelluriumSteadyStateStep", {"model": MODEL}, outputs={"steady_state_concentrations": ["c"]}), "c": {},
             "em": node("step", "RAMEmitter", {"emit": {"c": "map"}}, inputs={"c": ["c"]})}
    r = run(Document(source="t", form="composite-file", state=state))
    assert r.status == "translatable", r.reasons
    assert r.sed2["tasks"]["s"]["_type"] == "steadyState" and r.kind == "steady-state"


def _process_doc(header=None, interval=1.0):
    state = {"sim": node("process", "TelluriumProcess", {"model": MODEL}, outputs={"species": ["sp"], "time": ["t"]}, interval=interval),
             "sp": {}, "t": 0.0,
             "em": node("step", "RAMEmitter", {"emit": {"species": "map", "time": "float"}}, inputs={"species": ["sp"], "time": ["t"]})}
    return Document(source="t", form="composite-file", state=state, header=header or {})


def test_process_without_run_length_gets_duration_1_in_constants():
    r = run(_process_doc())
    assert r.status == "translatable", r.reasons
    assert r.sed2["constants"] == {"duration": 1}
    assert r.sed2["tasks"]["s"]["independentVariableRange"] == {"_type": "numericRange", "start": 0.0, "end": "#constants:duration", "interval": 1.0}
    assert list(r.sed2)[:2] == ["version", "constants"]
    assert r.run_length["value"] == 1.0 and "default 1" in r.run_length["source"]


def test_process_run_length_order_option_header_callers_default():
    from pbg2sed2.callers import RunLength
    found = lambda doc: RunLength(7.0, "a script", [])
    assert run(_process_doc(), duration=3.0, find_run_length=found).sed2["constants"] == {"duration": 3}
    assert run(_process_doc({"default_n_steps": 2}, interval=0.5), find_run_length=found).sed2["constants"] == {"duration": 1}
    r = run(_process_doc(), find_run_length=found)
    assert r.sed2["constants"] == {"duration": 7} and "a caller of the document: a script" in r.run_length["source"]
    r = run(_process_doc(), find_run_length=lambda doc: RunLength(None, "nothing found", []))
    assert r.sed2["constants"] == {"duration": 1} and "nothing found" in r.run_length["source"]


def test_run_length_must_be_whole_intervals():
    r = run(_process_doc(interval=2.0))
    assert r.status == "not-translatable" and "whole number of intervals" in r.reasons[0]
    assert run(_process_doc(), duration=2.5).status == "not-translatable"
    assert run(_process_doc(interval=2.0), duration=4.0).sed2["constants"] == {"duration": 4}


def test_templates_and_unresolved_parameters_are_refused():
    d = utc_doc()
    d.is_template = True
    assert run(d).status == "not-translatable"
    d = utc_doc()
    d.unresolved = ["x"]
    assert "without a default" in run(d).reasons[0]


def test_refused_result_writes_the_report_and_no_sed2(tmp_path):
    r = run(utc_doc({"integrator": "gillespie"}))
    assert write_result(r, tmp_path / "x.sed2.json", tmp_path / "x.import.json") == EXIT_NOT_TRANSLATABLE
    assert not (tmp_path / "x.sed2.json").exists()
    assert json.loads((tmp_path / "x.import.json").read_text())["status"] == "not-translatable"
