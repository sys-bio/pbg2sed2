"""Static reader: turn files into `Document` objects without importing or running any foreign code.

Source forms handled (plan, section 3): composite files (JSON or YAML) with a header and `${name}` parameters;
bundles (a JSON or YAML mapping from a name to a document); document literals inside Python files and notebooks
(found with `ast`, evaluated tolerantly: anything that is not a literal becomes an `Unresolved` marker and the
document is marked incomplete).  Template files are recognised by name and reported, not interpreted.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_.\-]*)\}")
TEMPLATE_SUFFIXES = (".template.yaml", ".template.yml", ".template.json")
COMPOSITE_SUFFIXES = (".composite.yaml", ".composite.yml", ".composite.json")
NODE_TYPES = ("process", "step")


class Unresolved(str):
    """A value in a Python literal that is not a literal (a name, a call, an f-string, ...)."""


@dataclass
class Document:
    source: str                       # label, normally repository-relative path (plus a locator for literals)
    form: str                         # composite-file | bundle-entry | python-literal | notebook-literal | template-file
    header: dict = field(default_factory=dict)
    state: dict = field(default_factory=dict)
    schema: Any = None
    shape: str = "state-tree"         # state-tree | schema-state
    resolved: list[str] = field(default_factory=list)      # placeholders replaced by their defaults
    unresolved: list[str] = field(default_factory=list)    # placeholders without a default
    complete: bool = True             # False when a Python literal contained non-literal expressions
    unresolved_exprs: list[str] = field(default_factory=list)
    fragment: bool = False            # a single node dict, not a whole document
    is_template: bool = False
    notes: list[str] = field(default_factory=list)


def is_node(value: Any) -> bool:
    return isinstance(value, dict) and value.get("_type") in NODE_TYPES


def contains_node(value: Any) -> bool:
    if isinstance(value, dict):
        if is_node(value):
            return True
        return any(contains_node(v) for k, v in value.items() if not (isinstance(k, str) and k.startswith("_") and k != "_value"))
    if isinstance(value, (list, tuple)):
        return any(contains_node(v) for v in value)
    return False


def _substitute(value: Any, defaults: dict, resolved: set, unresolved: set, depth: int = 0) -> Any:
    """Replace ${name} by the parameter's value.  A value that itself contains placeholders is resolved in turn, so a
    default such as "${model_dir}/m.xml" reports `model_dir` when that has no value (the loader of the document's own
    package may supply it; here it must be given, see `overrides`)."""
    if isinstance(value, Unresolved):
        return value
    if isinstance(value, str):
        whole = PLACEHOLDER.fullmatch(value)
        if whole:
            name = whole.group(1)
            if name in defaults:
                resolved.add(name)
                return _substitute(defaults[name], defaults, resolved, unresolved, depth + 1) if depth < 8 else defaults[name]
            unresolved.add(name)
            return value

        def one(m):
            name = m.group(1)
            if name in defaults:
                resolved.add(name)
                inner = _substitute(defaults[name], defaults, resolved, unresolved, depth + 1) if depth < 8 else defaults[name]
                return str(inner)
            unresolved.add(name)
            return m.group(0)

        return PLACEHOLDER.sub(one, value)
    if isinstance(value, dict):
        return {k: _substitute(v, defaults, resolved, unresolved, depth) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute(v, defaults, resolved, unresolved, depth) for v in value]
    return value


def parameter_defaults(header: dict) -> dict:
    out = {}
    params = header.get("parameters") if isinstance(header, dict) else None
    if isinstance(params, dict):
        for name, spec in params.items():
            if isinstance(spec, dict):
                if "default" in spec:
                    out[name] = spec["default"]
            else:
                out[name] = spec
    return out


def document_from_mapping(raw: dict, source: str, form: str, overrides: dict | None = None) -> Document | None:
    """Build a Document from a parsed mapping, or None when it does not look like a document.

    `overrides` gives values for parameters (they win over the header's defaults), the way a loader's overrides do."""
    if not isinstance(raw, dict):
        return None
    header = {k: v for k, v in raw.items() if k not in ("state", "schema")}
    if "state" in raw and isinstance(raw["state"], dict):
        state = raw["state"]
        shape = "schema-state" if "schema" in raw else "state-tree"
        schema = raw.get("schema")
    elif contains_node(raw):
        state, shape, schema, header = raw, "state-tree", None, {}
    else:
        return None
    defaults = {**parameter_defaults(header), **(overrides or {})}
    resolved: set = set()
    unresolved: set = set()
    state = _substitute(state, defaults, resolved, unresolved)
    return Document(source=source, form=form, header=header, state=state, schema=schema, shape=shape,
                    resolved=sorted(resolved), unresolved=sorted(unresolved))


def _parse_text(path: Path) -> Any:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        return json.loads(text)
    return yaml.safe_load(text)


def load_composite_file(path: Path, label: str | None = None, overrides: dict | None = None) -> tuple[list[Document], list[str]]:
    """Read a composite or bundle file.  Returns (documents, notes)."""
    label = label or str(path)
    name = path.name.lower()
    notes: list[str] = []
    try:
        raw = _parse_text(path)
    except Exception as exc:  # unreadable file: report, do not guess
        return [], [f"unreadable: {type(exc).__name__}: {str(exc)[:120]}"]
    if name.endswith(TEMPLATE_SUFFIXES):
        doc = document_from_mapping(raw, label, "template-file", overrides) if isinstance(raw, dict) else None
        if doc is None:
            return [], ["template file with no recognisable state"]
        doc.is_template = True
        doc.notes.append("template: open sites are not interpreted by this reader")
        return [doc], notes
    if isinstance(raw, dict) and "state" in raw:
        doc = document_from_mapping(raw, label, "composite-file", overrides)
        return ([doc] if doc else []), notes
    if isinstance(raw, dict) and raw and all(isinstance(v, dict) and "state" in v for v in raw.values()):
        docs = [document_from_mapping(v, f"{label}#{k}", "bundle-entry", overrides) for k, v in raw.items()]
        return [d for d in docs if d], notes
    doc = document_from_mapping(raw, label, "composite-file", overrides) if isinstance(raw, dict) else None
    if doc is None:
        return [], ["parsed, but no state and no process or step node"]
    return [doc], notes


# ---------------------------------------------------------------- Python and notebook literals

def _tolerant(node: ast.AST, notes: list[str]) -> Any:
    """Evaluate an AST node as far as it is a literal; everything else becomes an Unresolved marker."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Dict):
        out: dict = {}
        for k, v in zip(node.keys, node.values):
            if k is None:  # {**other}
                notes.append("dict unpacking: " + ast.unparse(v)[:60])
                continue
            key = _tolerant(k, notes)
            if not isinstance(key, (str, int, float, bool)) or isinstance(key, Unresolved):
                key = "<key: " + ast.unparse(k)[:40] + ">"
            out[key] = _tolerant(v, notes)
        return out
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return [_tolerant(e, notes) for e in node.elts]
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)) and isinstance(node.operand, ast.Constant) \
            and isinstance(node.operand.value, (int, float)):
        return -node.operand.value if isinstance(node.op, ast.USub) else node.operand.value
    text = ast.unparse(node)
    notes.append(text[:80])
    return Unresolved("<unresolved: " + text[:80] + ">")


def _dict_has_node(node: ast.AST) -> bool:
    """True when a Dict node holds, through dict values, lists and tuples only, a dict with `_type` process or step."""
    if isinstance(node, ast.Dict):
        for k, v in zip(node.keys, node.values):
            if isinstance(k, ast.Constant) and k.value == "_type" and isinstance(v, ast.Constant) and v.value in NODE_TYPES:
                return True
        return any(_dict_has_node(v) for v in node.values)
    if isinstance(node, (ast.List, ast.Tuple)):
        return any(_dict_has_node(e) for e in node.elts)
    return False


def _top_dicts(tree: ast.AST):
    """Outermost Dict nodes that contain a node dict (not descending into a Dict once found)."""
    if isinstance(tree, ast.Dict) and _dict_has_node(tree):
        yield tree
        return
    for child in ast.iter_child_nodes(tree):
        yield from _top_dicts(child)


def extract_python_literals(text: str, label: str, form: str = "python-literal") -> tuple[list[Document], list[str]]:
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return [], [f"python syntax error: {exc.msg} (line {exc.lineno})"]
    docs: list[Document] = []
    for d in _top_dicts(tree):
        notes: list[str] = []
        value = _tolerant(d, notes)
        if not isinstance(value, dict):
            continue
        loc = f"{label}:{d.lineno}"
        fragment = is_node(value)
        if fragment:
            doc = Document(source=loc, form=form, state={"_fragment": value}, fragment=True)
        else:
            doc = document_from_mapping(value, loc, form)
            if doc is None:
                continue
        doc.form = form
        doc.complete = not notes
        doc.unresolved_exprs = notes[:20]
        docs.append(doc)
    return docs, []


def load_python_file(path: Path, label: str | None = None) -> tuple[list[Document], list[str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        return [], [f"unreadable: {type(exc).__name__}"]
    if "_type" not in text:
        return [], []
    return extract_python_literals(text, label or str(path))


def load_notebook(path: Path, label: str | None = None) -> tuple[list[Document], list[str]]:
    label = label or str(path)
    try:
        nb = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [], [f"unreadable notebook: {type(exc).__name__}"]
    docs: list[Document] = []
    notes: list[str] = []
    for i, cell in enumerate(nb.get("cells", [])):
        if cell.get("cell_type") != "code":
            continue
        src = cell.get("source", "")
        src = "".join(src) if isinstance(src, list) else src
        if "_type" not in src:
            continue
        lines = [ln for ln in src.splitlines() if not ln.lstrip().startswith(("%", "!"))]
        d, n = extract_python_literals("\n".join(lines), f"{label}[cell {i}]", form="notebook-literal")
        docs.extend(d)
        notes.extend(n)
    return docs, notes


def load_path(path: Path, label: str | None = None, overrides: dict | None = None) -> tuple[list[Document], list[str]]:
    """Dispatch on the file name.  Study files are not documents; they are handled by the survey."""
    name = path.name.lower()
    if name.endswith(TEMPLATE_SUFFIXES + COMPOSITE_SUFFIXES):
        return load_composite_file(path, label, overrides)
    if name.endswith(".py"):
        return load_python_file(path, label)
    if name.endswith(".ipynb"):
        return load_notebook(path, label)
    if name.endswith((".json", ".yaml", ".yml")):
        return load_composite_file(path, label, overrides)
    return [], []
