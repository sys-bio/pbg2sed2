"""Tests on real documents of the vivarium-collective repositories, fetched on demand (corpus/manifest.json)."""

import json
from pathlib import Path

import pytest

from pbg2sed2.classify import classify
from pbg2sed2.mapping import Options, translate
from pbg2sed2.reader import load_path

pytest.importorskip("libsbml")
pytest.importorskip("antimony")

TELLURIUM = ["viva-tellurium:decay-demo.composite.yaml", "viva-tellurium:decay-with-viz.composite.yaml", "viva-tellurium:steady-state.composite.yaml"]
COPASI = ["viva-copasi:utc-step.composite.yaml", "viva-copasi:utc-process.composite.yaml", "viva-copasi:steady-state.composite.yaml"]
OPENCOR = ["viva-opencor:decay.composite.yaml", "viva-opencor:van-der-pol.composite.yaml"]


def read(corpus_doc, entry_id, copasi=False):
    path = corpus_doc(entry_id)
    overrides = {"model_dir": str(path.parent)} if copasi else None
    docs, _ = load_path(path, path.name, overrides)
    assert len(docs) == 1
    return docs[0], path


def run(corpus_doc, entry_id, **kw):
    if entry_id.startswith("viva-copasi"):
        corpus_doc("viva-copasi:repressilator.xml")          # the bundled model sits beside the documents
    doc, path = read(corpus_doc, entry_id, copasi=entry_id.startswith("viva-copasi"))
    return translate(doc, classify(doc), Options(name="t", base_dir=path.parent, **kw))


@pytest.mark.parametrize("entry_id", TELLURIUM + COPASI + OPENCOR)
def test_wrapper_documents_are_tier_a(corpus_doc, entry_id):
    doc, _ = read(corpus_doc, entry_id, copasi=entry_id.startswith("viva-copasi"))
    c = classify(doc)
    assert c.tier == "A", c.reasons
    assert doc.unresolved == [] and doc.complete


def test_tellurium_decay_demo(corpus_doc):
    r = run(corpus_doc, TELLURIUM[0], duration=3.0)
    assert r.status == "translatable", r.reasons
    s = r.sed2["tasks"]["s"]
    assert s["outputVariables"] == ["S1", "S2", "_J0", "k"]
    assert s["independentVariableRange"] == {"_type": "numericRange", "start": 0.0, "end": "#constants:duration", "interval": 1.0}
    assert r.sed2["constants"] == {"duration": 3}
    assert r.sed2["tasks"]["c"]["setValues"] == {"S1": 10.0, "k": 0.3}


def test_tellurium_decay_demo_without_run_length_gets_the_default_1(corpus_doc):
    r = run(corpus_doc, TELLURIUM[0])
    assert r.status == "translatable", r.reasons
    assert r.sed2["constants"] == {"duration": 1} and "default 1" in r.run_length["source"]


def test_tellurium_decay_with_viz_is_refused_because_of_its_plot(corpus_doc):
    r = run(corpus_doc, TELLURIUM[1], duration=3.0)
    assert r.status == "not-translatable" and r.sed2 is None and r.dropped


def test_tellurium_steady_state(corpus_doc):
    r = run(corpus_doc, TELLURIUM[2])
    assert r.status == "translatable" and r.sed2["tasks"]["s"]["_type"] == "steadyState"


def test_copasi_utc_step_columns(corpus_doc):
    r = run(corpus_doc, COPASI[0])
    assert r.status == "translatable", r.reasons
    ids = r.sed2["tasks"]["s"]["outputVariables"]
    assert ids[:6] == ["PX", "PY", "PZ", "X", "Y", "Z"] and "beta" in ids and len(ids) == 15
    assert r.sed2["tasks"]["s"]["independentVariableRange"] == {"_type": "numericRange", "start": 0.0, "end": 10.0, "numberOfSteps": 10}


def test_copasi_steady_state_reads_fluxes_by_name(corpus_doc):
    r = run(corpus_doc, COPASI[2])
    assert r.status == "translatable"
    assert r.sed2["tasks"]["s"]["outputVariables"][-1] == "Reaction12" and r.labels["transcription of CI"] == "Reaction12"


def test_copasi_utc_process_translates(corpus_doc):
    r = run(corpus_doc, COPASI[1], duration=3.0)
    assert r.status == "translatable", r.reasons
    assert r.tick == 1.0 and r.sed2["constants"] == {"duration": 3}
    assert r.sed2["tasks"]["s"]["independentVariableRange"]["end"] == "#constants:duration"


def test_copasi_document_without_model_dir_is_refused(corpus_doc):
    path = corpus_doc(COPASI[0])
    docs, _ = load_path(path, path.name)
    doc = docs[0]
    r = translate(doc, classify(doc), Options(name="t", base_dir=path.parent))
    assert r.status == "not-translatable" and "model_dir" in r.reasons[0]


@pytest.mark.parametrize("entry_id", OPENCOR)
def test_opencor_documents_are_recognised_but_not_mapped(corpus_doc, entry_id):
    r = run(corpus_doc, entry_id)
    assert r.status == "not-translatable" and "not mapped yet" in r.reasons[0]
