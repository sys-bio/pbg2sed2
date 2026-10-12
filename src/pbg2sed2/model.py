"""Models named by a document: load them as SBML text and read their element lists (libsbml; Antimony through libAntimony).

Nothing from the surveyed repositories is imported here.  The optional dependencies are python-libsbml and antimony
(extra `emit`); a missing one is reported as a refusal, never worked around.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


class ModelError(Exception):
    """The model cannot be loaded or read; the message is the reason that goes into the report."""


@dataclass
class ModelInfo:
    sbml: str
    source: str                                  # where it came from, for the report
    floating_species: list[str] = field(default_factory=list)
    boundary_species: list[str] = field(default_factory=list)
    reactions: list[str] = field(default_factory=list)
    parameters: list[str] = field(default_factory=list)
    compartments: dict[str, float] = field(default_factory=dict)
    compartment_constant: dict[str, bool] = field(default_factory=dict)
    has_only_substance_units: dict[str, bool] = field(default_factory=dict)
    has_events: bool = False
    converted_from: str = ""                     # "antimony" when libAntimony produced the SBML
    reaction_labels: dict[str, str] = field(default_factory=dict)      # reaction id -> its name, or the id when it has none
    parameter_constant: dict[str, bool] = field(default_factory=dict)  # global parameter id -> constant
    uses_time: bool = False                      # some math refers to the time symbol


def unit_volumes(info: ModelInfo) -> bool:
    """Every compartment has size 1 and keeps it: then a species' amount and concentration are the same number, and the
    different readings of a species id (amount for hasOnlySubstanceUnits, concentration otherwise) cannot disagree."""
    return all(v == 1.0 and info.compartment_constant.get(c, False) for c, v in info.compartments.items())


def antimony_to_sbml(text: str) -> str:
    try:
        import antimony
    except ImportError as exc:
        raise ModelError("the model is Antimony and the antimony package is not installed") from exc
    antimony.clearPreviousLoads()
    if antimony.loadAntimonyString(text) < 0:
        raise ModelError("libAntimony cannot read the model: " + antimony.getLastError().strip()[:200])
    return antimony.getSBMLString(antimony.getMainModuleName())


def read_sbml(sbml: str, source: str, converted_from: str = "") -> ModelInfo:
    try:
        import libsbml
    except ImportError as exc:
        raise ModelError("python-libsbml is not installed; cannot read the model's elements") from exc
    doc = libsbml.readSBMLFromString(sbml)
    if doc.getNumErrors(libsbml.LIBSBML_SEV_FATAL) or doc.getModel() is None:
        raise ModelError("the SBML cannot be parsed")
    m = doc.getModel()
    info = ModelInfo(sbml=sbml, source=source, converted_from=converted_from)
    for i in range(m.getNumSpecies()):
        s = m.getSpecies(i)
        (info.boundary_species if s.getBoundaryCondition() else info.floating_species).append(s.getId())
        info.has_only_substance_units[s.getId()] = bool(s.getHasOnlySubstanceUnits())
    info.reactions = [m.getReaction(i).getId() for i in range(m.getNumReactions())]
    info.parameters = [m.getParameter(i).getId() for i in range(m.getNumParameters())]
    for i in range(m.getNumCompartments()):
        c = m.getCompartment(i)
        info.compartments[c.getId()] = c.getSize() if c.isSetSize() else float("nan")
        info.compartment_constant[c.getId()] = bool(c.getConstant())
    info.has_events = m.getNumEvents() > 0
    for i in range(m.getNumReactions()):
        r = m.getReaction(i)
        info.reaction_labels[r.getId()] = r.getName() or r.getId()
    for i in range(m.getNumParameters()):
        p = m.getParameter(i)
        info.parameter_constant[p.getId()] = bool(p.getConstant())
    info.uses_time = _uses_time(m)
    return info


def _uses_time(m) -> bool:
    import libsbml

    def has_time(ast) -> bool:
        if ast is None:
            return False
        if ast.getType() == libsbml.AST_NAME_TIME:
            return True
        return any(has_time(ast.getChild(i)) for i in range(ast.getNumChildren()))

    for i in range(m.getNumReactions()):
        kl = m.getReaction(i).getKineticLaw()
        if kl is not None and has_time(kl.getMath()):
            return True
    for coll in (m.getListOfRules(), m.getListOfInitialAssignments(), m.getListOfFunctionDefinitions(), m.getListOfConstraints()):
        if any(has_time(e.getMath()) for e in coll):
            return True
    for i in range(m.getNumEvents()):
        ev = m.getEvent(i)
        if (ev.getTrigger() is not None and has_time(ev.getTrigger().getMath())) or any(has_time(a.getMath()) for a in ev.getListOfEventAssignments()):
            return True
    return False


def load_model_source(model_source: str, base_dir: Path | None) -> ModelInfo:
    """Resolve a COPASI-style `model_source`: raw SBML text, or a path to an SBML file.  URLs are not fetched and COPASI
    (.cps) files are not read; both are refused with the reason."""
    text = (model_source or "").strip()
    if not text:
        raise ModelError("the config has no model_source")
    if text.startswith("<"):
        if "<sbml" not in text[:2000]:
            raise ModelError("model_source is XML text but not SBML (a COPASI document is not read)")
        return read_sbml(model_source, "inline SBML")
    if text.startswith(("http://", "https://")):
        raise ModelError(f"model_source is a URL ({text}); the importer does not fetch models")
    p = Path(text)
    if not p.is_absolute():
        p = (base_dir or Path.cwd()) / p
    if not p.exists():
        raise ModelError(f"model_source {text!r} not found (looked at {p}); pass --base-dir")
    content = p.read_text(encoding="utf-8")
    if "<sbml" not in content[:4000]:
        raise ModelError(f"{p.name} is not an SBML file (a COPASI document is not read)")
    return read_sbml(content, f"file {text}")


def load_model(cfg: dict, base_dir: Path | None) -> ModelInfo:
    """Resolve the model of a Tellurium-style config (`model`, `model_format`, `model_file`)."""
    model_file = cfg.get("model_file") or ""
    if model_file:
        p = Path(model_file)
        if not p.is_absolute():
            p = (base_dir or Path.cwd()) / p
        if not p.exists():
            raise ModelError(f"model_file {model_file!r} not found (looked at {p}); pass --base-dir")
        text = p.read_text(encoding="utf-8")
        if str(model_file).endswith((".ant", ".txt")):
            return read_sbml(antimony_to_sbml(text), f"file {model_file}", "antimony")
        return read_sbml(text, f"file {model_file}")
    src = cfg.get("model") or ""
    if not src:
        raise ModelError("the config has neither model nor model_file")
    fmt = cfg.get("model_format") or "antimony"
    if fmt == "sbml":
        if src.lstrip().startswith("<"):
            return read_sbml(src, "inline SBML")
        raise ModelError("model_format sbml with a path in `model`: not mapped (use model_file)")
    if fmt != "antimony":
        raise ModelError(f"model_format {fmt!r} is not mapped")
    return read_sbml(antimony_to_sbml(src), "inline Antimony", "antimony")
