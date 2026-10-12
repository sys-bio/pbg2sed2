"""Mapping of tier A documents to SED2 (phase R3).

Handlers exist for the viva-tellurium step and process classes.  A document is translatable only when every node has
a mapping, and the result says exactly what was mapped, dropped or unsupported.  A construct that is not mapped is
refused with its reason; nothing is approximated.  Handlers are conservative: each precondition that would make a
mapped document mean something else than the original is checked and refused when it fails.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from .callers import RunLength
from .classify import Classification, NodeInfo, SIMULATOR_ROLES, _wire_paths
from .clock import to_decimal
from .model import ModelError, ModelInfo, load_model, load_model_source, unit_volumes
from .reader import Document

SBML = "urn:sedml:language:sbml"
TIME = "urn:sedml:symbol:time"
RAM_EMITTERS = ("RAMEmitter", "ram-emitter")


class Refuse(Exception):
    """A construct that is not mapped; the message is the reason that goes into the report."""


@dataclass
class Options:
    name: str = "doc"
    duration: float | None = None
    base_dir: Path | None = None
    # called with the document when it gives no run length and none was passed: looks for callers that run it
    find_run_length: Callable[[Document], RunLength | None] | None = None


@dataclass
class Entry:
    path: str
    cls: str
    what: str

    def to_json(self) -> dict:
        return {"path": self.path, "class": self.cls, "what": self.what}


@dataclass
class Group:
    ids: list[str]                 # SED2 variable ids this simulator port stands for; [] for time
    is_time: bool = False


@dataclass
class Plan:
    model: ModelInfo
    changes: dict[str, float]
    sim: dict                      # the simulation task, without "model"
    groups: dict[str, Group]       # simulator output port -> group
    kind: str                      # process-ticks | trajectory | steady-state
    notes: list[str] = field(default_factory=list)
    labels: dict[str, str] = field(default_factory=dict)   # the original's column label -> SED2 id, where they differ
    tick: float | None = None      # process: the interval, so that rows without a time port can be given one
    constants: dict[str, Any] = field(default_factory=dict)   # SED2 constants the simulation refers to
    run_length: dict | None = None  # process: where the run length came from


@dataclass
class Result:
    status: str                    # translatable | not-translatable (a document is translated whole or not at all)
    sed2: dict | None = None
    model_files: dict[str, str] = field(default_factory=dict)
    mapped: list[Entry] = field(default_factory=list)
    dropped: list[Entry] = field(default_factory=list)
    unsupported: list[Entry] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    source: str = ""
    tier: str = ""
    columns: list[str] = field(default_factory=list)       # report columns in order, for the verification
    kind: str = ""
    labels: dict[str, str] = field(default_factory=dict)
    tick: float | None = None
    run_length: dict | None = None

    def report(self) -> dict:
        return {"source": self.source, "tier": self.tier, "status": self.status, "reasons": self.reasons, "notes": self.notes,
                "mapped": [e.to_json() for e in self.mapped], "dropped": [e.to_json() for e in self.dropped],
                "unsupported": [e.to_json() for e in self.unsupported], "columns": self.columns, "run_length": self.run_length}


def _num(v: Any, what: str) -> float:
    d = to_decimal(v)
    if d is None:
        raise Refuse(f"{what} is not a number: {v!r}")
    return float(d)


def _check_overrides(cfg: dict, model: ModelInfo) -> dict[str, float]:
    changes: dict[str, float] = {}
    sp = cfg.get("species_overrides") or {}
    pa = cfg.get("parameter_overrides") or {}
    if sp:
        if not unit_volumes(model):
            raise Refuse("species_overrides set the wrapper's species value (an amount) while SED2 sets a concentration; they agree only when every compartment has constant size 1, which this model does not satisfy")
        for sid, v in sp.items():
            if sid not in model.floating_species:
                raise Refuse(f"species_overrides names {sid!r}, which is not a floating species of the model")
            changes[sid] = _num(v, f"species_overrides[{sid}]")
    for pid, v in pa.items():
        if pid not in model.parameters:
            raise Refuse(f"parameter_overrides names {pid!r}, which is not a global parameter of the model")
        changes[pid] = _num(v, f"parameter_overrides[{pid}]")
    return changes


def _tellurium_common(node: NodeInfo, opts: Options) -> tuple[ModelInfo, dict[str, float]]:
    cfg = node.config
    if (cfg.get("integrator") or "cvode") != "cvode":
        raise Refuse(f"integrator {cfg.get('integrator')!r}: only the deterministic cvode integrator is mapped (stochastic tasks are not in scope yet)")
    if cfg.get("selections"):
        raise Refuse("config.selections (roadrunner selection strings) are not mapped yet")
    if (cfg.get("species_units") or "concentration") != "concentration":
        raise Refuse("species_units 'amount' is not mapped: SED2 species ids mean concentrations")
    try:
        model = load_model(cfg, opts.base_dir)
    except ModelError as exc:
        raise Refuse(str(exc)) from exc
    if model.has_events:
        raise Refuse("the model has SBML events; the mapping has not been checked against the wrapper's behaviour with events")
    if any(model.has_only_substance_units.get(s, False) for s in model.floating_species) and not unit_volumes(model):
        raise Refuse("a floating species has hasOnlySubstanceUnits and a compartment does not have constant size 1: the wrapper reports concentrations and SED2 ids mean amounts for such species")
    return model, _check_overrides(cfg, model)


def _tolerances(cfg: dict) -> dict:
    return {"relativeTolerance": _num(cfg.get("relative_tolerance", 1e-8), "relative_tolerance"),
            "absoluteTolerance": _num(cfg.get("absolute_tolerance", 1e-10), "absolute_tolerance")}


def h_tellurium_utc_step(node: NodeInfo, doc: Document, opts: Options) -> Plan:
    cfg = node.config
    if cfg.get("output_times"):
        raise Refuse("config.output_times (explicit non-uniform output points) is not mapped yet")
    model, changes = _tellurium_common(node, opts)
    n_points = int(_num(cfg.get("n_points", 101), "n_points"))
    if n_points < 2:
        raise Refuse("n_points < 2")
    sim = {"_type": "explicitODESimulation", "independentVariable": TIME,
           "independentVariableRange": {"_type": "numericRange", "start": _num(cfg.get("start_time", 0.0), "start_time"),
                                        "end": _num(cfg.get("end_time", 10.0), "end_time"), "numberOfSteps": n_points - 1},
           **_tolerances(cfg)}
    groups = {"time_series": Group([], True), "species_trajectories": Group(list(model.floating_species))}
    return Plan(model, changes, sim, groups, "trajectory", ["n_points points become numberOfSteps = n_points - 1"])


def h_tellurium_steady(node: NodeInfo, doc: Document, opts: Options) -> Plan:
    cfg = node.config
    if cfg.get("steady_state_options"):
        raise Refuse("config.steady_state_options (roadrunner solver options) are not mapped")
    model, changes = _tellurium_common(node, opts)
    return Plan(model, changes, {"_type": "steadyState"}, {"steady_state_concentrations": Group(list(model.floating_species))},
                "steady-state", ["the wrapper calls roadrunner's steadyState() with default solver settings; SED2's steadyState leaves the algorithm to the backend"])


def _ticks(node: NodeInfo, doc: Document, opts: Options) -> tuple[Decimal, Decimal, list[str], dict]:
    """The interval, the run length, the notes and the record of where the run length came from, for a process node.

    process-bigraph takes the run length from the caller.  Order: `--duration`; the header's `default_n_steps` times the
    interval; the numeric `run(T)` of a script that calls the document (found by `find_run_length`); else 1."""
    dt = to_decimal(node.interval) if node.interval is not None else Decimal("1.0")
    if dt is None or dt <= 0:
        raise Refuse(f"the process interval is not a positive number: {node.interval!r}")
    notes = []
    if node.interval is None:
        notes.append("the process gives no interval; process-bigraph's default 1.0 is used")
    info: dict
    if opts.duration is not None:
        total = Decimal(str(opts.duration))
        info = {"value": float(total), "source": "given on the command line", "candidates": []}
    elif "default_n_steps" in doc.header:
        total = dt * Decimal(str(doc.header["default_n_steps"]))
        info = {"value": float(total), "source": f"the header's default_n_steps = {doc.header['default_n_steps']} times the interval", "candidates": []}
    else:
        found = opts.find_run_length(doc) if opts.find_run_length else None
        if found is not None and found.value is not None:
            total = Decimal(str(found.value))
            info = {"value": found.value, "source": "a caller of the document: " + found.source, "candidates": [c.to_json() for c in found.candidates]}
        else:
            total = Decimal(1)
            why = found.source if found is not None else "no search for callers was made"
            info = {"value": 1.0, "source": f"the default 1 ({why})", "candidates": []}
    notes.append(f"the run length {total} (constants:duration) is from {info['source']}; edit the constant to run longer")
    ratio = total / dt
    if ratio != ratio.to_integral_value() or ratio < 1:
        raise Refuse(f"the run length {total} ({info['source']}) is not a whole number of intervals of {dt}; give --duration")
    return dt, total, notes, info


def _duration_range(dt: Decimal) -> dict:
    return {"_type": "numericRange", "start": 0.0, "end": "#constants:duration", "interval": float(dt)}


def _duration_constant(total: Decimal) -> dict:
    return {"duration": int(total) if total == total.to_integral_value() else float(total)}


def h_tellurium_process(node: NodeInfo, doc: Document, opts: Options) -> Plan:
    model, changes = _tellurium_common(node, opts)
    dt, total, notes, info = _ticks(node, doc, opts)
    sim = {"_type": "explicitODESimulation", "independentVariable": TIME, "independentVariableRange": _duration_range(dt),
           **_tolerances(node.config)}
    notes.append("the process restarts the integrator at every interval and keeps its instance; SED2 integrates the whole span in one task, so values agree only to the integrator's tolerance (clock analysis, G5)")
    notes.append("the original's emitter records an empty row at t = 0 (the stores are filled by the first update); the SED2 report starts with the model's initial state at t = 0")
    groups = {"species": Group(list(model.floating_species)), "rates": Group(list(model.reactions)),
              "parameters": Group(list(model.parameters)), "time": Group([], True)}
    return Plan(model, changes, sim, groups, "process-ticks", notes, tick=float(dt), constants=_duration_constant(total), run_length=info)


# ---------------------------------------------------------------- COPASI wrappers (viva-copasi)

_COPASI_ODE_METHODS = (None, "", "deterministic", "lsoda")


def _store_value(doc: Document, wire: Any) -> Any:
    cur: Any = doc.state
    for k in (wire if isinstance(wire, (list, tuple)) else []):
        if isinstance(cur, dict) and k in cur:
            cur = cur[k]
        else:
            return None
    return cur


def _copasi_common(node: NodeInfo, doc: Document, opts: Options, time_course: bool) -> ModelInfo:
    cfg = node.config
    if time_course and (cfg.get("method") or None) not in _COPASI_ODE_METHODS:
        raise Refuse(f"method {cfg.get('method')!r}: only the default deterministic (LSODA) method is mapped")
    for key in ("selections", "output_times", "step_size"):
        if cfg.get(key):
            raise Refuse(f"config.{key} is not mapped yet")
    if (cfg.get("species_units") or "concentration") != "concentration":
        raise Refuse("species_units 'amount' is not mapped: SED2 species ids mean concentrations")
    for port, wire in node.inputs.items():
        v = _store_value(doc, wire)
        if v not in (None, {}, []):
            raise Refuse(f"input port {port!r} reads store {list(wire)}, which holds {v!r} at the start; values from input stores are applied as initial concentrations by the wrapper and are not mapped yet")
    try:
        model = load_model_source(cfg.get("model_source") or "", opts.base_dir)
    except ModelError as exc:
        raise Refuse(str(exc)) from exc
    if model.has_events:
        raise Refuse("the model has SBML events; the mapping has not been checked against the wrapper's behaviour with events")
    if any(model.has_only_substance_units.get(sid, False) for sid in model.floating_species + model.boundary_species) and not unit_volumes(model):
        raise Refuse("a species has hasOnlySubstanceUnits and a compartment does not have constant size 1: the wrapper reports concentrations and SED2 ids mean amounts for such species")
    return model


def _copasi_tolerances(cfg: dict) -> dict:
    out = {}
    if cfg.get("relative_tolerance") is not None:
        out["relativeTolerance"] = _num(cfg["relative_tolerance"], "relative_tolerance")
    if cfg.get("absolute_tolerance") is not None:
        out["absoluteTolerance"] = _num(cfg["absolute_tolerance"], "absolute_tolerance")
    return out


def _all_species(model: ModelInfo) -> list[str]:
    return model.floating_species + model.boundary_species


def h_copasi_utc_step(node: NodeInfo, doc: Document, opts: Options) -> Plan:
    cfg = node.config
    model = _copasi_common(node, doc, opts, True)
    n_points = int(_num(cfg.get("n_points", 2), "n_points"))
    if n_points < 2:
        raise Refuse("n_points < 2")
    start = _num(cfg.get("start_time") or 0.0, "start_time")
    duration = _num(cfg.get("time", 1.0), "time")
    sim = {"_type": "explicitODESimulation", "independentVariable": TIME,
           "independentVariableRange": {"_type": "numericRange", "start": start, "end": start + duration, "numberOfSteps": n_points - 1},
           **_copasi_tolerances(cfg)}
    # basico's default time-course output: the species and the global quantities that are not fixed.
    ids = _all_species(model) + [p for p in model.parameters if not model.parameter_constant.get(p, True)]
    notes = ["`time` is a duration: the range runs from start_time to start_time + time; n_points points become numberOfSteps = n_points - 1",
             "the columns are predicted as the species and the non-constant global parameters (basico's default output); the verification checks this against the original"]
    return Plan(model, {}, sim, {"result": Group(ids)}, "trajectory", notes)


def h_copasi_steady(node: NodeInfo, doc: Document, opts: Options) -> Plan:
    cfg = node.config
    opt_keys = ("relative_tolerance", "criterion", "derivation_factor", "iteration_limit", "use_newton", "use_integration",
                "use_back_integration", "accept_negative_concentrations", "forward_integration_duration", "backward_integration_duration")
    given = [k for k in opt_keys if cfg.get(k) is not None and cfg.get(k) != ""]
    if given:
        raise Refuse("steady-state options are not mapped: " + ", ".join(given))
    model = _copasi_common(node, doc, opts, False)
    labels = {model.reaction_labels[r]: r for r in model.reactions}
    groups = {"results": Group(_all_species(model) + list(model.reactions))}
    return Plan(model, {}, {"_type": "steadyState"}, groups, "steady-state",
                ["the wrapper runs COPASI's steady-state task with its default settings; SED2's steadyState leaves the algorithm to the backend",
                 "the wrapper keys fluxes by the reactions' names; the SED2 ids are the SBML ids"], labels=labels)


def h_copasi_process(node: NodeInfo, doc: Document, opts: Options) -> Plan:
    cfg = node.config
    model = _copasi_common(node, doc, opts, True)
    if model.uses_time:
        raise Refuse("the model's math refers to time, and the wrapper restarts the model clock at start_time at every update; SED2 integrates continuously, so the two differ")
    dt, total, notes, info = _ticks(node, doc, opts)
    sim = {"_type": "explicitODESimulation", "independentVariable": TIME, "independentVariableRange": _duration_range(dt),
           **_copasi_tolerances(cfg)}
    notes.append("the process continues the model state at every interval (update_model) and runs COPASI once per interval; SED2 integrates the whole span in one task, so values agree only to the integrator's tolerance (clock analysis, G5)")
    notes.append("config.time and config.intervals do not change the dynamics: the duration of an update is the process interval")
    groups = {"species_concentrations": Group(_all_species(model)), "fluxes": Group(list(model.reactions)), "time": Group([], True)}
    labels = {model.reaction_labels[r]: r for r in model.reactions}
    return Plan(model, {}, sim, groups, "process-ticks", notes, labels=labels, tick=float(dt), constants=_duration_constant(total), run_length=info)


HANDLERS: dict[str, Callable[[NodeInfo, Document, Options], Plan]] = {
    "TelluriumUTCStep": h_tellurium_utc_step,
    "TelluriumSteadyStateStep": h_tellurium_steady,
    "TelluriumProcess": h_tellurium_process,
    "CopasiUTCStep": h_copasi_utc_step,
    "CopasiSteadyStateStep": h_copasi_steady,
    "CopasiUTCProcess": h_copasi_process,
}


def _refused(r: Result, reasons: list[str], cls: Classification | None = None) -> Result:
    r.status = "not-translatable"
    r.reasons = reasons
    return r


def translate(doc: Document, cls: Classification, opts: Options | None = None) -> Result:
    opts = opts or Options()
    r = Result(status="not-translatable", source=doc.source, tier=cls.tier)
    if doc.is_template:
        return _refused(r, ["a template with open sites"])
    if doc.fragment or not cls.nodes:
        return _refused(r, ["not a document: " + "; ".join(cls.reasons)])
    if not doc.complete:
        return _refused(r, ["the document literal contains expressions that are not literals: " + "; ".join(doc.unresolved_exprs[:3])])
    if doc.unresolved:
        return _refused(r, ["parameters without a default: " + ", ".join(doc.unresolved)])
    if cls.tier != "A":
        return _refused(r, [f"tier {cls.tier}: " + "; ".join(cls.reasons)])
    sims = [n for n in cls.nodes if n.role in SIMULATOR_ROLES]
    if len(sims) != 1:
        return _refused(r, [f"{len(sims)} simulator nodes; only one is mapped"])
    sim = sims[0]
    handler = HANDLERS.get(sim.cls)
    if handler is None:
        return _refused(r, [f"{sim.cls} is recognised but not mapped yet"])
    try:
        plan = handler(sim, doc, opts)
    except Refuse as exc:
        return _refused(r, [f"{sim.cls}: {exc}"])

    spath = "/".join(map(str, sim.path))
    out_wires = {port: tuple(w) for port, w in sim.outputs.items() if isinstance(w, (list, tuple))}
    emitters = [n for n in cls.nodes if n.role == "emitter"]
    ram = [e for e in emitters if e.cls in RAM_EMITTERS]
    for e in emitters:
        if e.cls not in RAM_EMITTERS:
            r.unsupported.append(Entry("/".join(map(str, e.path)), e.cls, "an emitter that stores data elsewhere: a storage choice SED2 does not model"))
    if len(ram) != 1:
        return _refused(r, [f"{len(ram)} in-memory emitters; exactly one is mapped" + (" (nothing is observed without one)" if not ram else "")] )
    em = ram[0]
    epath = "/".join(map(str, em.path))
    ids: list[str] = []
    columns: list[str] = ["time"]
    for eport, wire in em.inputs.items():
        p = tuple(wire) if isinstance(wire, (list, tuple)) else None
        src = next((q for q, w in out_wires.items() if w == p), None)
        if p is None or src is None or src not in plan.groups:
            r.unsupported.append(Entry(epath, em.cls, f"emitter port {eport!r} reads {list(p) if p else wire!r}, which no mapped output of {sim.cls} writes"))
            continue
        g = plan.groups[src]
        if g.is_time:
            r.mapped.append(Entry(epath, em.cls, f"port {eport!r} <- {sim.cls}.{src}: the report's time column"))
            continue
        for v in g.ids:
            if v not in ids:
                ids.append(v)
        r.mapped.append(Entry(epath, em.cls, f"port {eport!r} <- {sim.cls}.{src}: {len(g.ids)} variables"))
    if not ids:
        return _refused(r, ["nothing the emitter observes could be mapped"] + [e.what for e in r.unsupported])
    columns += ids

    for n in cls.nodes:
        if n is sim or n is em or n.role == "emitter":
            continue
        r.dropped.append(Entry("/".join(map(str, n.path)), n.cls, f"role {n.role}: not translated in this version"))

    model_file = f"{opts.name}.model.sbml"
    tasks: dict[str, Any] = {"m": {"_type": "modelImport", "location": model_file, "language": SBML}}
    model_ref = "#tasks:m.model"
    if plan.changes:
        tasks["c"] = {"_type": "modelChange", "inputModel": model_ref, "setValues": dict(plan.changes)}
        model_ref = "#tasks:c.model"
    simdef = {"_type": plan.sim["_type"], "model": model_ref}
    if plan.sim["_type"] == "steadyState":
        simdef["outputVariables"] = ids
    else:
        simdef["independentVariable"] = plan.sim["independentVariable"]
        simdef["outputVariables"] = ids
        for k, v in plan.sim.items():
            if k not in simdef:
                simdef[k] = v
    tasks["s"] = simdef
    r.sed2 = {"version": "v1.0.0"}
    if plan.constants:
        r.sed2["constants"] = dict(plan.constants)       # constants come before the tasks that refer to them
    r.sed2["tasks"] = tasks
    r.sed2["outputs"] = {"r": {"_type": "report", "data": "#tasks:s"}}
    r.model_files = {model_file: plan.model.sbml}
    r.mapped.append(Entry(spath, sim.cls, f"-> {simdef['_type']} on the model from {plan.model.source}" + (" converted with libAntimony" if plan.model.converted_from else "")))
    if plan.changes:
        r.mapped.append(Entry(spath, sim.cls, "species_overrides/parameter_overrides -> modelChange setValues: " + ", ".join(sorted(plan.changes))))
    r.notes = plan.notes
    r.columns = columns if plan.sim["_type"] != "steadyState" else ids
    r.kind = plan.kind
    r.labels = plan.labels
    r.tick = plan.tick
    r.run_length = plan.run_length
    r.status = "translatable"
    if r.dropped or r.unsupported:
        # Partial translation is not done: a document with a part that has no translation is refused as a whole, and the
        # report lists the parts (`dropped`, `unsupported`) next to the reason.
        parts = [f"{e.cls} at {e.path}" for e in r.dropped + r.unsupported]
        r.status = "not-translatable"
        r.reasons = ["part of the document has no translation, and a document is translated whole or not at all: " + "; ".join(parts)]
        r.sed2 = None
        r.model_files = {}
    return r
