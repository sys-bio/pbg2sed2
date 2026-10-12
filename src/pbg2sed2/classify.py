"""Classify the nodes of a document and give the document a provisional tier (plan, section 2).

Static only.  Roles come from `known_classes.json` by class name; anything else is opaque and counted as such.
The tier is a provisional label with reasons, never a verdict: it exists to order the survey, not to decide a
translation.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from importlib import resources
from typing import Any, Iterator

from .reader import Document, NODE_TYPES, Unresolved

SIMULATOR_ROLES = ("simulator-process", "simulator-step", "steady-state-step")
IGNORABLE_ROLES = ("emitter", "visualization", "drawing", "declarative-math")


def load_table() -> list[dict]:
    with resources.files("pbg2sed2").joinpath("known_classes.json").open("r", encoding="utf-8") as fh:
        return json.load(fh)["classes"]


_TABLE: list[dict] | None = None


def table() -> list[dict]:
    global _TABLE
    if _TABLE is None:
        _TABLE = load_table()
    return _TABLE


def class_name(address: Any) -> str:
    """'local:Foo' -> 'Foo'; 'local:!pkg.mod.Foo' -> 'Foo'; 'git:...#Foo' left to the last dotted component."""
    if isinstance(address, Unresolved):
        return "(address not a literal)"
    if not isinstance(address, str) or not address:
        return "(no address)"
    a = address.split(":", 1)[1] if ":" in address else address
    a = a.lstrip("!")
    return re.split(r"[.#/]", a)[-1]


def lookup(name: str, kind: str) -> dict | None:
    if not name or name.startswith("("):
        return None
    for entry in table():
        if name in entry.get("names", []) and entry.get("kind", "any") in ("any", kind):
            return entry
    for entry in table():
        pat = entry.get("pattern")
        if pat and re.search(pat, name) and entry.get("kind", "any") in ("any", kind):
            return entry
    return None


@dataclass
class NodeInfo:
    path: tuple
    kind: str                     # process | step
    address: str
    cls: str
    role: str                     # a role from the table, or 'opaque'
    known: bool
    entry: dict | None
    interval: Any                 # raw value of the interval key (None when absent)
    config: dict
    inputs: dict
    outputs: dict
    nested: bool = False          # found inside another node's config state

    def to_json(self) -> dict:
        return {"path": "/".join(map(str, self.path)), "kind": self.kind, "address": self.address, "class": self.cls,
                "role": self.role, "known": self.known, "interval": _jsonable(self.interval), "nested": self.nested}


def _jsonable(v: Any) -> Any:
    return str(v) if isinstance(v, Unresolved) else v


def iter_nodes(state: Any, path: tuple = (), nested: bool = False) -> Iterator[NodeInfo]:
    if not isinstance(state, dict):
        return
    for key, value in state.items():
        if not isinstance(value, dict):
            continue
        if isinstance(key, str) and key.startswith("_") and key != "_fragment":
            continue
        p = path + (key,)
        if value.get("_type") in NODE_TYPES:
            kind = value["_type"]
            addr = value.get("address", "")
            cls = class_name(addr)
            entry = lookup(cls, kind)
            cfg = value.get("config") if isinstance(value.get("config"), dict) else {}
            yield NodeInfo(path=p, kind=kind, address=str(addr), cls=cls, role=entry["role"] if entry else "opaque",
                           known=entry is not None, entry=entry, interval=value.get("interval"), config=cfg,
                           inputs=value.get("inputs") if isinstance(value.get("inputs"), dict) else {},
                           outputs=value.get("outputs") if isinstance(value.get("outputs"), dict) else {},
                           nested=nested)
            inner = cfg.get("state") if isinstance(cfg, dict) else None
            if isinstance(inner, dict):
                yield from iter_nodes(inner, p + ("config", "state"), True)
        else:
            yield from iter_nodes(value, p, nested)


def _as_path(wire: Any) -> tuple | None:
    if isinstance(wire, (list, tuple)) and all(isinstance(x, (str, int)) for x in wire):
        return tuple(wire)
    return None


def _wire_paths(ports: dict) -> list[tuple]:
    out = []
    for w in ports.values():
        p = _as_path(w)
        if p is not None:
            out.append(p)
        elif isinstance(w, dict):
            out.extend(_wire_paths(w))
    return out


@dataclass
class Classification:
    nodes: list[NodeInfo]
    tier: str
    reasons: list[str] = field(default_factory=list)
    opaque_classes: list[str] = field(default_factory=list)
    roles: dict = field(default_factory=dict)
    coupled: bool = False
    shared_stores: list[dict] = field(default_factory=list)


def shared_stores(nodes: list[NodeInfo]) -> list[dict]:
    """Stores written by one process-or-step node and touched by another one (excluding emitters and drawings)."""
    touched: dict[tuple, dict] = {}
    for n in nodes:
        if n.role in ("emitter", "visualization", "drawing"):
            continue
        for p in _wire_paths(n.outputs):
            touched.setdefault(p, {"writers": set(), "readers": set()})["writers"].add(n.path)
        for p in _wire_paths(n.inputs):
            touched.setdefault(p, {"writers": set(), "readers": set()})["readers"].add(n.path)
    out = []
    for p, rw in touched.items():
        users = rw["writers"] | rw["readers"]
        if rw["writers"] and len(users) > 1:
            out.append({"store": "/".join(map(str, p)), "writers": sorted("/".join(map(str, w)) for w in rw["writers"]),
                        "readers": sorted("/".join(map(str, r)) for r in rw["readers"])})
    return sorted(out, key=lambda d: d["store"])


def classify(doc: Document) -> Classification:
    nodes = list(iter_nodes(doc.state))
    roles: dict[str, int] = {}
    for n in nodes:
        roles[n.role] = roles.get(n.role, 0) + 1
    reasons: list[str] = []
    opaque = sorted({n.cls or n.address for n in nodes if n.role == "opaque"})
    stores = shared_stores([n for n in nodes if n.role != "composite"])
    working = [n for n in nodes if n.role not in IGNORABLE_ROLES and n.role != "composite"]
    procs = [n for n in working if n.kind == "process"]
    coupled = bool(stores) and len(working) > 1

    if doc.is_template:
        return Classification(nodes, "template", ["template file: open sites"], opaque, roles, coupled, stores)
    if doc.fragment:
        return Classification(nodes, "fragment", ["a single node, not a document"], opaque, roles, coupled, stores)
    if not nodes:
        return Classification(nodes, "none", ["no process or step node"], opaque, roles, coupled, stores)
    if roles.get("forward-translator"):
        return Classification(nodes, "C", ["contains classes of this project's forward translator"], opaque, roles, coupled, stores)
    if roles.get("drawing") and not working:
        return Classification(nodes, "none", ["drawing composite: only draft nodes, not simulated"], opaque, roles, coupled, stores)
    if any(n.role == "coupled-model" for n in nodes):
        reasons.append("contains a coupled, spatial or agent model class: " + ", ".join(sorted({n.cls for n in nodes if n.role == 'coupled-model'})))
        return Classification(nodes, "D", reasons, opaque, roles, coupled, stores)
    if opaque:
        if coupled or len(procs) > 1:
            reasons.append("opaque classes and more than one working node wired together: " + ", ".join(opaque))
            return Classification(nodes, "D", reasons, opaque, roles, coupled, stores)
        reasons.append("opaque classes: " + ", ".join(opaque))
        return Classification(nodes, "E", reasons, opaque, roles, coupled, stores)
    sims = [n for n in working if n.role in SIMULATOR_ROLES]
    stateful = [n for n in working if n.role == "stateful-utility"]
    if sims:
        sim_paths = {"/".join(map(str, n.path)) for n in sims}
        math_paths = {"/".join(map(str, n.path)) for n in working if n.role == "declarative-math"}
        coupling = [d for d in stores
                    if (set(d["writers"]) | set(d["readers"])) & sim_paths
                    and len((set(d["writers"]) | set(d["readers"])) - math_paths) > 1]
        if coupling:
            reasons.append("simulator nodes share stores with other working nodes: " + ", ".join(d["store"] for d in coupling[:5]))
            return Classification(nodes, "D", reasons, opaque, roles, True, stores)
        reasons.append("known simulator node(s), no coupling found: " + ", ".join(sorted({n.cls for n in sims})))
        return Classification(nodes, "A", reasons, opaque, roles, coupled, stores)
    if stateful:
        reasons.append("only stores and stateful utility classes: " + ", ".join(sorted({n.cls for n in stateful})))
        return Classification(nodes, "B", reasons, opaque, roles, coupled, stores)
    reasons.append("stores and declarative steps only")
    return Classification(nodes, "B", reasons, opaque, roles, coupled, stores)
