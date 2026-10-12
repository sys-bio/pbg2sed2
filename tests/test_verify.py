import pytest

from conftest import need

from pbg2sed2.verify import compare, read_report


def test_read_report_time_course_and_vector():
    cols, rows = read_report([["urn:sedml:symbol:time", "S1"], ["0.0", "1.0"], ["1.0", "0.5"]])
    assert cols == ["time", "S1"] and rows == [[0.0, 1.0], [1.0, 0.5]]
    cols, rows = read_report([["S1", "2.5e-23"], ["S2", "10.0"]])
    assert cols == ["S1", "S2"] and rows == [[2.5e-23, 10.0]]


def test_compare_joins_on_time_and_counts_the_extra_sed2_row():
    orig = (["time", "x"], [[1.0, 2.0], [2.0, 3.0]])
    new = (["time", "x"], [[0.0, 1.0], [1.0, 2.0], [2.0, 3.5]])
    c = compare(orig, new, "process-ticks", 1e-6, 1e-4, empty_dropped=1)
    assert not c.ok and c.sed2_rows_without_original == 1 and c.rows_compared == 2 and c.worst == "x@2.0"


def test_compare_flags_a_column_the_sed2_lacks():
    c = compare((["S1", "S2"], [[1.0, 2.0]]), (["S1"], [[1.0]]), "steady-state", 1e-6, 1e-4)
    assert not c.ok and c.only_original == ["S2"]


def test_verification_against_the_real_original():
    need("process_bigraph")
    need("viva_tellurium")
    from pbg2sed2.classify import classify
    from pbg2sed2.mapping import Options, translate
    from pbg2sed2.reader import Document
    from pbg2sed2.verify import run_original, original_table
    model = "model m\n  S1 = 10; S2 = 0\n  S1 -> S2; k*S1; k = 0.3\nend\n"
    state = {"sim": {"_type": "step", "address": "local:TelluriumSteadyStateStep", "config": {"model": model}, "inputs": {},
                     "outputs": {"steady_state_concentrations": ["c"]}}, "c": {},
             "em": {"_type": "step", "address": "local:RAMEmitter", "config": {"emit": {"c": "map[float]"}}, "inputs": {"c": ["c"]}}}
    doc = Document(source="t", form="composite-file", state=state)
    res = translate(doc, classify(doc), Options(name="t"))
    assert res.status == "translatable"
    table, _ = original_table(run_original(doc, 0.0), res.kind)
    assert table[0] == ["S1", "S2"] and abs(table[1][0][1] - 10.0) < 1e-6
