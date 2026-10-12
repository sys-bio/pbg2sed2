"""The clock-usage record of one document: what the survey must count to test the clock proposals.

The items are the table "What to record per document" in the clock analysis (`process-bigraph-clock.md`, section 8).
Everything here is read from the document; what only the Python class or the run driver shows (an overridden
`calculate_timestep`, the `run(...)` call) cannot be seen in a document and is recorded elsewhere or as unknown.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from .classify import Classification, NodeInfo, _wire_paths
from .reader import Document, Unresolved

DEFAULT_INTERVAL = Decimal("1.0")   # process-bigraph's default interval for a process that gives none (read in 1.8.5)
STRUCTURAL_KEYS = ("_add", "_remove", "_divide")


def to_decimal(value: Any) -> Decimal | None:
    """Exact decimal reading of an interval as written; None when it is not a number."""
    if isinstance(value, bool) or isinstance(value, Unresolved):
        return None
    if isinstance(value, (int, float, str)):
        try:
            return Decimal(str(value).strip())
        except InvalidOperation:
            return None
    return None


def common_grid(values: list[Decimal]) -> Decimal | None:
    """Largest decimal tick that divides every value exactly (the gcd), in exact arithmetic; None for non-positive input."""
    vals = sorted(set(values))
    if not vals or vals[0] <= 0:
        return None
    exp = max(-v.normalize().as_tuple().exponent for v in vals)
    exp = max(exp, 0)
    scale = Decimal(10) ** exp
    ints = [int((v * scale).to_integral_value()) for v in vals]
    from math import gcd
    g = 0
    for i in ints:
        g = gcd(g, i)
    return Decimal(g) / scale


def interval_kind(values: list[Decimal]) -> dict:
    """Classify a set of intervals in exact decimal arithmetic.

    'single': one value.  'integer-multiples': every value is an integer multiple of the smallest (nested loops can
    express it today).  'common-grid': no integer ratio to the smallest, but a common tick exists (always true for
    decimals), so the clock proposal P2 can express it with a range whose step is that tick and `every` counts.
    """
    distinct = sorted(set(values))
    if len(distinct) <= 1:
        return {"kind": "single"}
    grid = common_grid(distinct)
    if grid is None:
        return {"kind": "invalid"}
    smallest = distinct[0]
    ints = all((v / smallest) == (v / smallest).to_integral_value() for v in distinct)
    return {"kind": "integer-multiples" if ints else "common-grid", "grid": str(grid),
            "every": {str(v): str(int(v / grid)) for v in distinct}}


def _count_keys(value: Any, keys: tuple) -> int:
    n = 0
    if isinstance(value, dict):
        for k, v in value.items():
            if k in keys:
                n += 1
            n += _count_keys(v, keys)
    elif isinstance(value, list):
        for v in value:
            n += _count_keys(v, keys)
    return n


def clock_record(doc: Document, cls: Classification) -> dict:
    procs = [n for n in cls.nodes if n.kind == "process" and n.role not in ("composite", "drawing")]
    steps = [n for n in cls.nodes if n.kind == "step"]
    intervals: list[Decimal] = []
    unknown_intervals = 0
    defaulted = 0
    per_process = []
    for n in procs:
        if n.interval is None:
            iv, how = DEFAULT_INTERVAL, "default"
            defaulted += 1
        else:
            iv = to_decimal(n.interval)
            how = "given" if iv is not None else "unresolved"
        if iv is None:
            unknown_intervals += 1
        else:
            intervals.append(iv)
        per_process.append({"path": "/".join(map(str, n.path)), "class": n.cls, "interval": None if iv is None else str(iv), "how": how})

    process_paths = {n.path for n in procs}
    interval_wired = []
    for s in steps:
        for p in _wire_paths(s.outputs):
            if p and p[-1] == "interval" and p[:-1] in process_paths:
                interval_wired.append({"step": "/".join(map(str, s.path)), "process": "/".join(map(str, p[:-1]))})
    reads_interval = ["/".join(map(str, n.path)) for n in cls.nodes
                      if "interval" in n.inputs or any(p and p[-1] == "interval" for p in _wire_paths(n.inputs))]
    hidden = sorted({n.cls for n in procs if n.entry and n.entry.get("hidden_state")})
    unknown_state = sorted({n.cls or n.address for n in procs if n.role == "opaque"})
    windows = sorted({n.cls for n in cls.nodes if (n.entry and n.entry.get("time_gated")) or "window" in n.config
                      or n.config.get("use_global_time") is True})
    reads_global_time = ["/".join(map(str, n.path)) for n in cls.nodes if ("global_time",) in _wire_paths(n.inputs)]

    # steps with no process upstream: not reachable from any process output by following steps
    written = set()
    for n in procs:
        written.update(_wire_paths(n.outputs))
    downstream: set = set()
    changed = True
    live = set(written)
    while changed:
        changed = False
        for s in steps:
            if s.path in downstream:
                continue
            if any(p in live or any(p[:len(w)] == w or w[:len(p)] == p for w in live) for p in _wire_paths(s.inputs)):
                downstream.add(s.path)
                live.update(_wire_paths(s.outputs))
                changed = True
    upstream_free = ["/".join(map(str, s.path)) for s in steps if s.path not in downstream and s.role not in ("drawing",)]

    equal_interval_shared = []
    by_path = {"/".join(map(str, n.path)): n for n in procs}
    for d in cls.shared_stores:
        writers = [w for w in d["writers"] if w in by_path]
        if len(writers) > 1 or (writers and any(r in by_path and r not in writers for r in d["readers"])):
            ivs = {to_decimal(by_path[w].interval) if by_path[w].interval is not None else DEFAULT_INTERVAL for w in writers}
            equal_interval_shared.append({"store": d["store"], "writers": writers, "readers": d["readers"],
                                          "writer_intervals": sorted(str(i) for i in ivs if i is not None)})

    return {
        "processes": per_process,
        "interval_kind": interval_kind(intervals)["kind"] if intervals else ("none" if not procs else "unknown"),
        "interval_grid": interval_kind(intervals) if intervals else None,
        "intervals_defaulted": defaulted,
        "intervals_unresolved": unknown_intervals,
        "step_wired_to_process_interval": interval_wired,
        "nodes_reading_an_interval": reads_interval,
        "nodes_reading_global_time": reads_global_time,
        "hidden_state_classes_known": hidden,
        "classes_with_unknown_state": unknown_state,
        "time_windows": windows,
        "shared_stores_between_processes": equal_interval_shared,
        "structural_sentinels": _count_keys(doc.state, STRUCTURAL_KEYS),
        "steps_without_process_upstream": upstream_free,
        "parallel_processes_flag": bool(doc.state.get("parallel_processes") or doc.header.get("parallel_processes")),
        "run_length_in_document": "default_n_steps" if "default_n_steps" in doc.header else "not stated",
    }
