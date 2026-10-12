"""Verification (phase R4): run the original document and the translated SED2 and compare their data.

This module RUNS foreign code (the original document's process classes, through process_bigraph) and the generated
script of pysed2translate.  It is used only by the verification command, in an environment prepared for the document's
tier, never by the reader or the survey.  A disagreement is reported with its size; nothing is tuned to remove it.
"""

from __future__ import annotations

import csv
import json
import math
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from .classify import iter_nodes
from .mapping import Result
from .reader import Document

Table = tuple[list[str], list[list[float]]]   # columns, rows


# The registration function each wrapper package offers to build a core in which its classes and types exist.  This is
# the package's own entry point (what its loader calls), not something this tool invents.
REGISTER = {
    "Tellurium": ("viva_tellurium.composites", "register_tellurium"),
    "Copasi": ("viva_copasi.composites", "register_copasi"),
}


def make_core(doc: Document):
    """A core with the wrapper packages' classes registered for the classes the document uses."""
    import importlib
    from process_bigraph import allocate_core
    core = allocate_core()
    seen: set[str] = set()
    for node in iter_nodes(doc.state):
        for prefix, (mod, fn) in REGISTER.items():
            if node.cls.startswith(prefix) and mod not in seen:
                seen.add(mod)
                core = getattr(importlib.import_module(mod), fn)(core)
    return core


def run_original(doc: Document, run_time: float) -> list[dict]:
    """Run the document with process_bigraph for run_time and return the in-memory emitter's rows."""
    from process_bigraph import Composite
    from process_bigraph.emitter import gather_emitter_results
    sim = Composite({"state": doc.state}, core=make_core(doc))
    sim.run(run_time)
    results = gather_emitter_results(sim)
    if len(results) != 1:
        raise RuntimeError(f"expected one emitter, found {sorted(map(str, results))}")
    return next(iter(results.values()))


def _scalar(x):
    return x[0] if isinstance(x, list) and len(x) == 1 else x


def original_table(rows: list[dict], kind: str, labels: dict[str, str] | None = None, tick: float | None = None) -> tuple[Table, int]:
    """The original's data as a table, and the number of rows dropped because they were empty (the t = 0 row of a process).

    `labels` renames the original's column labels to the SED2 ids (COPASI keys fluxes by reaction name); `tick` gives
    rows of a process a time (row i is at i * tick) when the document does not emit one.
    """
    labels = labels or {}
    empty = 0
    kept: list[tuple[int, dict]] = []
    for i, r in enumerate(rows):
        maps = [v for v in r.values() if isinstance(v, dict)]
        if maps and all(not m for m in maps):
            empty += 1
            continue
        kept.append((i, r))
    if not kept:
        return ([], []), empty

    def rename(name: str) -> str:
        return labels.get(name, name)

    if kind == "trajectory":
        row = kept[0][1]
        for port, v in row.items():       # a numeric_result: {time, columns, values}
            if isinstance(v, dict) and {"time", "columns", "values"} <= set(v):
                names = ["time"] + [rename(str(c)) for c in v["columns"]]
                return (names, [[float(t)] + [float(x) for x in vals] for t, vals in zip(v["time"], v["values"])]), empty
        flat = {}
        for port, v in row.items():
            if isinstance(v, dict):
                flat.update({str(k): x for k, x in v.items()})
            else:
                flat[str(port)] = v
        names = ["time"] + [rename(k) for k in flat if k != "time_series"]
        series = {("time" if k == "time_series" else rename(k)): v for k, v in flat.items()}
        n = len(series["time"])
        return (names, [[float(series[c][i]) for c in names] for i in range(n)]), empty
    flat_rows: list[dict] = []
    for i, r in kept:
        d: dict = {}
        for port, v in r.items():
            if isinstance(v, dict):
                for k, x in v.items():
                    if isinstance(x, dict):
                        d.update({rename(str(kk)): _scalar(xx) for kk, xx in x.items()})
                    elif k != "time" or kind != "steady-state":
                        d[rename(str(k))] = _scalar(x)
            elif port != "time" or kind != "steady-state":
                d[str(port)] = v
        if kind == "process-ticks" and "time" not in d and tick is not None:
            d["time"] = i * tick
        flat_rows.append(d)
    names = list(flat_rows[0])
    return (names, [[float(r[c]) for c in names] for r in flat_rows if all(c in r for c in names)]), empty


def run_sed2(sed2_path: Path, backend: str, python: str = sys.executable) -> Table:
    """Translate with pysed2translate and run the script; read the report `r` back."""
    with tempfile.TemporaryDirectory() as tmp:
        script = Path(tmp) / "s.py"
        prefix = "v"
        t = subprocess.run([python, "-m", "pysed2translate", str(sed2_path), "--backend", backend, "-o", str(script), "--prefix", prefix,
                            "--input-dir", str(sed2_path.parent.resolve())], capture_output=True, text=True)
        if t.returncode != 0:
            raise RuntimeError(f"pysed2translate exit {t.returncode}: {(t.stdout + t.stderr).strip()[:400]}")
        out = Path(tmp) / "out"
        r = subprocess.run([python, str(script), "--output-dir", str(out)], capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"generated script exit {r.returncode}: {(r.stdout + r.stderr).strip()[:400]}")
        with open(out / f"{prefix}.r.csv", newline="", encoding="utf-8") as fh:
            rows = list(csv.reader(fh))
    return read_report(rows)


def read_report(rows: list[list[str]]) -> Table:
    """A time course has a header row of labels (no cell numeric); a one-step or steady-state result is label,value lines.

    The first column of a time course is the independent variable; its label (urn:sedml:symbol:time) is read as `time`.
    """
    def numeric(x: str) -> bool:
        try:
            float(x)
            return True
        except ValueError:
            return False
    if rows and not any(numeric(x) for x in rows[0]):
        cols = list(rows[0])
        if cols[0] == "urn:sedml:symbol:time":
            cols[0] = "time"
        return cols, [[float(x) for x in r] for r in rows[1:]]
    return [r[0] for r in rows], [[float(r[1]) for r in rows]]


@dataclass
class Comparison:
    ok: bool
    columns_compared: list[str] = field(default_factory=list)
    only_original: list[str] = field(default_factory=list)
    only_sed2: list[str] = field(default_factory=list)
    rows_compared: int = 0
    original_rows_dropped_empty: int = 0
    sed2_rows_without_original: int = 0
    max_abs: float = 0.0
    max_rel: float = 0.0
    worst: str = ""
    notes: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return self.__dict__


def compare(orig: Table, new: Table, kind: str, abs_tol: float, rel_tol: float, empty_dropped: int = 0) -> Comparison:
    """|a - e| <= abs + rel * |e| with e from the original, per the suite's rule; rows are joined on the time column when there is one."""
    oc, orows = orig
    nc, nrows = new
    c = Comparison(ok=True, original_rows_dropped_empty=empty_dropped)
    c.columns_compared = [x for x in oc if x in nc]
    c.only_original = [x for x in oc if x not in nc]
    c.only_sed2 = [x for x in nc if x not in oc]
    if c.only_original:
        c.ok = False
    if kind == "steady-state":
        pairs = [(orows[0][oc.index(x)], nrows[0][nc.index(x)], x) for x in c.columns_compared]
    else:
        ti_o, ti_n = oc.index("time"), nc.index("time")
        by_time = {round(r[ti_n], 9): r for r in nrows}
        pairs = []
        used = set()
        for r in orows:
            key = round(r[ti_o], 9)
            m = by_time.get(key)
            if m is None:
                c.ok = False
                c.notes.append(f"no SED2 row at time {r[ti_o]}")
                continue
            used.add(key)
            for x in c.columns_compared:
                pairs.append((r[oc.index(x)], m[nc.index(x)], f"{x}@{r[ti_o]}"))
        c.sed2_rows_without_original = len(by_time) - len(used)
        c.rows_compared = len(used)
    if kind == "steady-state":
        c.rows_compared = 1
    for e, a, where in pairs:
        d = abs(a - e)
        rel = d / abs(e) if e else (0.0 if d == 0 else math.inf)
        if d > c.max_abs:
            c.max_abs, c.worst = d, where
        c.max_rel = max(c.max_rel, rel if d > abs_tol else 0.0)
        if d > abs_tol + rel_tol * abs(e):
            c.ok = False
    return c


def verify(doc: Document, result: Result, sed2_path: Path, backends: list[str], run_time: float, abs_tol: float = 1e-6,
           rel_tol: float = 1e-4, runner=None) -> dict:
    """`runner(sed2_path, backend) -> Table` runs the SED2 (default: the script of pysed2translate); a caller can give another."""
    runner = runner or run_sed2
    out: dict = {"source": doc.source, "kind": result.kind, "backends": {}}
    rows = run_original(doc, run_time)
    otable, empty = original_table(rows, result.kind, result.labels, result.tick)
    out["original_rows"] = len(otable[1])
    out["original_columns"] = otable[0]
    for b in backends:
        try:
            ntable = runner(sed2_path, b)
        except RuntimeError as exc:
            out["backends"][b] = {"error": str(exc)}
            continue
        out["backends"][b] = compare(otable, ntable, result.kind, abs_tol, rel_tol, empty).to_json()
    return out
