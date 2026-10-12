import json
from pathlib import Path

from pbg2sed2.reader import (Unresolved, document_from_mapping, extract_python_literals, load_composite_file, load_notebook,
                             load_path)

PROC = {"_type": "process", "address": "local:TelluriumProcess", "config": {"model_string": "${model}"}, "interval": "${dt}",
        "inputs": {}, "outputs": {"species": ["stores", "species"]}}


def test_placeholders_whole_and_embedded_are_resolved_to_defaults(tmp_path):
    raw = {"name": "d", "parameters": {"model": {"type": "string", "default": "A=1"}, "dt": {"default": 0.5}},
           "state": {"p": dict(PROC, config={"model_string": "${model}", "note": "x-${model}-y"}), "other": "${missing}"}}
    doc = document_from_mapping(raw, "d.composite.yaml", "composite-file")
    assert doc.state["p"]["config"]["model_string"] == "A=1"
    assert doc.state["p"]["config"]["note"] == "x-A=1-y"
    assert doc.state["p"]["interval"] == 0.5
    assert doc.resolved == ["dt", "model"]
    assert doc.unresolved == ["missing"]
    assert doc.state["other"] == "${missing}"  # left as written, recorded as unresolved


def test_schema_and_state_shape_is_recognised():
    doc = document_from_mapping({"schema": {"a": "float"}, "state": {"a": 1.0, "p": PROC}}, "x", "composite-file")
    assert doc.shape == "schema-state" and doc.schema == {"a": "float"}


def test_yaml_file_bundle_and_non_document(tmp_path):
    (tmp_path / "a.composite.yaml").write_text("name: a\nstate:\n  p:\n    _type: process\n    address: local:X\n", encoding="ascii")
    docs, notes = load_composite_file(tmp_path / "a.composite.yaml", "a.composite.yaml")
    assert len(docs) == 1 and docs[0].form == "composite-file"
    bundle = {"one.composite.yaml": {"state": {"p": PROC}}, "two.composite.yaml": {"state": {"q": PROC}}}
    (tmp_path / "b.json").write_text(json.dumps(bundle), encoding="ascii")
    docs, _ = load_composite_file(tmp_path / "b.json", "b.json")
    assert [d.form for d in docs] == ["bundle-entry", "bundle-entry"]
    assert docs[0].source == "b.json#one.composite.yaml"
    (tmp_path / "c.yaml").write_text("services:\n  web:\n    image: x\n", encoding="ascii")
    docs, notes = load_composite_file(tmp_path / "c.yaml", "c.yaml")
    assert docs == [] and notes


def test_template_file_is_reported_not_interpreted(tmp_path):
    (tmp_path / "t.template.yaml").write_text("state:\n  p:\n    _type: process\n    address: local:X\n", encoding="ascii")
    docs, _ = load_path(tmp_path / "t.template.yaml")
    assert docs[0].is_template and docs[0].form == "template-file"


def test_unreadable_file_is_reported(tmp_path):
    (tmp_path / "bad.composite.json").write_text("{not json", encoding="ascii")
    docs, notes = load_composite_file(tmp_path / "bad.composite.json")
    assert docs == [] and notes[0].startswith("unreadable")


def test_python_literal_is_extracted_and_marks_non_literals_incomplete():
    src = '''
dt = 0.5
doc = {"state": {"p": {"_type": "process", "address": "local:TelluriumProcess", "interval": dt,
                       "config": {"model_string": make_model()}, "inputs": {}, "outputs": {}}}}
'''
    docs, _ = extract_python_literals(src, "f.py")
    assert len(docs) == 1
    d = docs[0]
    assert not d.complete and d.unresolved_exprs
    assert isinstance(d.state["p"]["interval"], Unresolved)
    assert d.source == "f.py:3"


def test_python_single_node_is_a_fragment_and_plain_dicts_are_ignored():
    src = 'node = {"_type": "step", "address": "local:RAMEmitter"}\nother = {"a": 1}\n'
    docs, _ = extract_python_literals(src, "f.py")
    assert len(docs) == 1 and docs[0].fragment


def test_python_syntax_error_is_reported_not_raised():
    docs, notes = extract_python_literals("def (:\n", "f.py")
    assert docs == [] and "syntax error" in notes[0]


def test_notebook_cells_are_read_and_magics_skipped(tmp_path):
    nb = {"cells": [{"cell_type": "code", "source": ["%matplotlib inline\n", "d = {'state': {'p': {'_type': 'process', 'address': 'local:X'}}}\n"]},
                    {"cell_type": "markdown", "source": ["{'_type': 'process'}"]}]}
    (tmp_path / "n.ipynb").write_text(json.dumps(nb), encoding="ascii")
    docs, _ = load_notebook(tmp_path / "n.ipynb", "n.ipynb")
    assert len(docs) == 1 and docs[0].form == "notebook-literal" and "cell 0" in docs[0].source


def test_placeholder_inside_a_default_is_resolved_in_turn_and_reported():
    raw = {"parameters": {"src": {"default": "${dir}/m.xml"}}, "state": {"p": {"_type": "process", "address": "local:X", "config": {"model_source": "${src}", "other": "pre-${src}"}}}}
    doc = document_from_mapping(raw, "d", "composite-file")
    assert doc.unresolved == ["dir"] and doc.state["p"]["config"]["model_source"] == "${dir}/m.xml"
    doc = document_from_mapping(raw, "d", "composite-file", {"dir": "/x"})
    assert doc.unresolved == [] and doc.state["p"]["config"]["model_source"] == "/x/m.xml" and doc.state["p"]["config"]["other"] == "pre-/x/m.xml"
    doc = document_from_mapping(raw, "d", "composite-file", {"src": "/y.xml"})
    assert doc.state["p"]["config"]["model_source"] == "/y.xml" and doc.unresolved == []
