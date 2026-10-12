from pbg2sed2.callers import document_names, find_run_length, scan_source

NAMES = document_names("utc-process", "utc-process.composite.yaml")


def test_names():
    assert NAMES == {"utc-process", "utc-process.composite.yaml"}


def test_run_in_the_same_scope_as_the_call_that_names_the_document():
    src = "def f():\n    sim = build_composite('utc-process')\n    sim.run(12.5)\n"
    assert scan_source(src, NAMES) == [(3, 12.5)]
    assert scan_source("sim = load('x/utc-process.composite.yaml')\nsim.run(4)\n", NAMES) == [(2, 4.0)]


def test_other_scopes_comparisons_and_non_literals_do_not_count():
    assert scan_source("def f():\n    build_composite('utc-process')\ndef g():\n    sim.run(3.0)\n", NAMES) == []
    assert scan_source("assert 'utc-process' in specs\nsim.run(3.0)\n", NAMES) == []
    assert scan_source("sim = build_composite('utc-process')\nsim.run(T)\n", NAMES) == []
    assert scan_source("sim = build_composite('other')\nsim.run(3.0)\n", NAMES) == []
    assert scan_source("this is not python", NAMES) == []


def make(tmp_path):
    (tmp_path / "demo").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "demo" / "run.py").write_text("sim = build_composite('utc-process')\nsim.run(10.0)\n")
    (tmp_path / "tests" / "test_a.py").write_text("def test_a():\n    sim = build_composite('utc-process')\n    sim.run(2.0)\n")
    (tmp_path / "README.md").write_text("text\n```python\nsim = build_composite('utc-process')\nsim.run(5)\n```\n")
    nb = {"cells": [{"cell_type": "code", "source": ["sim = build_composite('utc-process')\n", "sim.run(7.0)\n"]}, {"cell_type": "markdown", "source": ["x"]}]}
    import json
    (tmp_path / "nb.ipynb").write_text(json.dumps(nb))
    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "skip.py").write_text("build_composite('utc-process')\nrun(99)\n")


def test_scripts_are_preferred_to_tests_and_the_candidates_are_listed(tmp_path):
    make(tmp_path)
    r = find_run_length(tmp_path, NAMES)
    assert r.value == 10.0                                          # script values occur once each: first in file order, the README snippet ranks below scripts
    assert sorted(c.value for c in r.candidates) == [2.0, 5.0, 7.0, 10.0] and "different values" in r.source
    assert [c.is_test for c in r.candidates if c.value == 2.0] == [True]


def test_only_tests_are_used_when_there_is_no_script(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_a.py").write_text("sim = build_composite('utc-process')\nsim.run(2.0)\n")
    r = find_run_length(tmp_path, NAMES)
    assert r.value == 2.0 and "tests" in r.source


def test_nothing_found(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    r = find_run_length(tmp_path, NAMES)
    assert r.value is None and "no caller" in r.source


def test_the_document_file_itself_is_skipped(tmp_path):
    (tmp_path / "a.md").write_text("```python\nbuild_composite('utc-process')\nrun(3)\n```\n")
    assert find_run_length(tmp_path, NAMES, skip=tmp_path / "a.md").value is None
