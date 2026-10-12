from decimal import Decimal as D

from pbg2sed2.classify import classify
from pbg2sed2.clock import clock_record, common_grid, interval_kind
from pbg2sed2.reader import Document


def node(kind, cls, inputs=None, outputs=None, config=None, **extra):
    d = {"_type": kind, "address": f"local:{cls}", "config": config or {}, "inputs": inputs or {}, "outputs": outputs or {}}
    d.update(extra)
    return d


def record(state, **kw):
    d = Document(source="t", form="composite-file", state=state, **kw)
    return clock_record(d, classify(d))


def test_interval_kinds_in_exact_decimal_arithmetic():
    assert interval_kind([D("1.0")])["kind"] == "single"
    assert interval_kind([D("1.0"), D("50.0")])["kind"] == "integer-multiples"
    k = interval_kind([D("0.1"), D("0.25")])
    assert k["kind"] == "common-grid" and k["grid"] == "0.05" and k["every"] == {"0.1": "2", "0.25": "5"}
    k = interval_kind([D("0.3"), D("0.5")])
    assert k["grid"] == "0.1" and k["every"] == {"0.3": "3", "0.5": "5"}
    # floating point would call 0.3 an inexact multiple of 0.1; decimals do not
    assert interval_kind([D("0.1"), D("0.3")])["kind"] == "integer-multiples"
    assert common_grid([D("0")]) is None


def test_default_interval_is_recorded_as_defaulted():
    r = record({"p": node("process", "Foo", outputs={"o": ["x"]})})
    assert r["intervals_defaulted"] == 1 and r["processes"][0]["interval"] == "1.0" and r["interval_kind"] == "single"


def test_string_intervals_are_read():
    r = record({"p": node("process", "Foo", interval="3.0"), "q": node("process", "Bar", interval=0.5)})
    assert r["interval_kind"] == "integer-multiples" or r["interval_kind"] == "common-grid"
    assert {p["interval"] for p in r["processes"]} == {"3.0", "0.5"}


def test_step_wired_to_a_process_interval_is_found():
    state = {"event": node("process", "Event", interval=3.0),
             "iv": node("step", "Wait", outputs={"interval": ["event", "interval"]})}
    assert record(state)["step_wired_to_process_interval"] == [{"step": "iv", "process": "event"}]


def test_node_reading_an_interval_and_global_time():
    state = {"c": node("process", "Crm", outputs={"interval": ["interval"]}),
             "f": node("step", "Fba", inputs={"interval": ["interval"], "t": ["global_time"]})}
    r = record(state)
    assert r["nodes_reading_an_interval"] == ["f"] and r["nodes_reading_global_time"] == ["f"]


def test_hidden_state_and_time_window_classes():
    state = {"iv": node("process", "Intervention", config={"window": [1, 2]}), "clk": node("process", "Clock")}
    r = record(state)
    assert r["hidden_state_classes_known"] == ["Clock", "Intervention"] and r["time_windows"] == ["Intervention"]


def test_structural_sentinels_and_run_length_and_flags():
    state = {"p": node("process", "Foo", outputs={"o": ["x"]}), "x": {"_add": {}, "y": {"_remove": []}}, "parallel_processes": True}
    r = record(state, header={"default_n_steps": 10})
    assert r["structural_sentinels"] == 2 and r["run_length_in_document"] == "default_n_steps" and r["parallel_processes_flag"]


def test_steps_with_no_process_upstream():
    state = {"p": node("process", "Foo", outputs={"o": ["x"]}), "x": 0.0, "y": 1.0,
             "down": node("step", "D", inputs={"i": ["x"]}, outputs={"o": ["z"]}),
             "down2": node("step", "E", inputs={"i": ["z"]}),
             "free": node("step", "F", inputs={"i": ["y"]})}
    assert record(state)["steps_without_process_upstream"] == ["free"]


def test_processes_sharing_a_store_report_writer_intervals():
    state = {"a": node("process", "A", inputs={"i": ["x"]}, outputs={"o": ["x"]}, interval=1.0),
             "b": node("process", "B", inputs={"i": ["x"]}, outputs={"o": ["x"]}, interval=2.0), "x": 0.0}
    r = record(state)
    s = r["shared_stores_between_processes"][0]
    assert s["store"] == "x" and s["writer_intervals"] == ["1.0", "2.0"]
