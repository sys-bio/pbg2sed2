"""Find how long the callers of a document run it (static; nothing is imported or executed).

process-bigraph takes the run length from the caller (`Composite.run(T)`), not from the document.  For a document that
does not give one, the importer looks in the repository that holds the document for code that names the document in a
call (`build_composite("utc-process")`, `load("decay-demo.composite.yaml")`) and, in the same code scope, calls `run(T)`
with a number.  Python files (each function body and the module level are scopes), notebooks (each code cell) and the
fenced Python blocks of Markdown files are read with `ast`.  Nothing is guessed: a candidate is a literal number in a
`run` call that shares a scope with a call naming the document.
"""

from __future__ import annotations

import ast
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

SKIP_DIRS = {".git", "build", "dist", "node_modules", "__pycache__", ".venv", "venv", "corpus-cache", "work", ".tox", ".eggs"}
FENCE = re.compile(r"```(?:python|py)\s*\n(.*?)```", re.S)


@dataclass
class Candidate:
    value: float
    where: str            # file:line
    is_test: bool

    def to_json(self) -> dict:
        return {"value": self.value, "where": self.where, "test": self.is_test}


@dataclass
class RunLength:
    value: float | None
    source: str                                   # how the value was chosen, for the report
    candidates: list[Candidate] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"value": self.value, "source": self.source, "candidates": [c.to_json() for c in self.candidates]}


def _is_test(path: Path) -> bool:
    return any(p in ("tests", "test") for p in path.parts) or path.name.startswith("test_") or path.name.endswith("_test.py")


def document_names(doc_name: str, file_name: str) -> set[str]:
    """The strings that identify a document in a call: its header name, its file name and the file name's stem."""
    names = {n for n in (doc_name, file_name) if n}
    for n in list(names):
        stem = n
        for suffix in (".composite.yaml", ".composite.json", ".composite.yml", ".yaml", ".json"):
            if stem.endswith(suffix):
                stem = stem[: -len(suffix)]
        if stem:
            names.add(stem)
    return names


def _number(node: ast.AST) -> float | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return float(node.value)
    return None


def _scopes(tree: ast.AST):
    """The module body and every function body, each without the nested function bodies."""
    def own_nodes(root, nested):
        stack = list(ast.iter_child_nodes(root))
        while stack:
            n = stack.pop()
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                nested.append(n)
                continue
            yield n
            stack.extend(ast.iter_child_nodes(n))
    todo = [tree]
    while todo:
        root = todo.pop()
        nested: list = []
        yield list(own_nodes(root, nested))
        todo.extend(nested)


def scan_source(source: str, names: set[str]) -> list[tuple[int, float]]:
    """(line, number) of each `run(number)` that shares a scope with a call that has the document's name as an argument."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    found: list[tuple[int, float]] = []
    for nodes in _scopes(tree):
        names_it = False
        runs: list[tuple[int, float]] = []
        for n in nodes:
            if not isinstance(n, ast.Call):
                continue
            args = list(n.args) + [k.value for k in n.keywords]
            if any(isinstance(a, ast.Constant) and isinstance(a.value, str) and (a.value in names or Path(a.value).name in names) for a in args):
                names_it = True
            f = n.func
            if (isinstance(f, ast.Attribute) and f.attr == "run") or (isinstance(f, ast.Name) and f.id == "run"):
                first = n.args[0] if n.args else next((k.value for k in n.keywords if k.arg in ("interval", "duration", "total_time", "T")), None)
                v = _number(first) if first is not None else None
                if v is not None and v > 0:
                    runs.append((n.lineno, v))
        if names_it:
            found.extend(runs)
    return found


def _code_pieces(path: Path):
    """(first line of the piece, source) for each piece of code a file holds."""
    try:
        if path.suffix == ".py":
            yield 1, path.read_text(encoding="utf-8", errors="replace")
        elif path.suffix == ".ipynb":
            nb = json.loads(path.read_text(encoding="utf-8"))
            for i, cell in enumerate(nb.get("cells", [])):
                if cell.get("cell_type") == "code":
                    src = cell.get("source", "")
                    yield i + 1, "".join(src) if isinstance(src, list) else src
        elif path.suffix == ".md":
            text = path.read_text(encoding="utf-8", errors="replace")
            for m in FENCE.finditer(text):
                yield text.count("\n", 0, m.start()) + 2, m.group(1)
    except (OSError, ValueError):
        return


def find_run_length(search_root: Path, names: set[str], skip: Path | None = None) -> RunLength:
    """Look through `search_root` for callers of a document with these names."""
    cands: list[Candidate] = []
    files = sorted(p for p in search_root.rglob("*") if p.is_file() and p.suffix in (".py", ".ipynb", ".md")
                   and not (set(p.relative_to(search_root).parts[:-1]) & SKIP_DIRS))
    for path in files:
        if skip is not None and path.resolve() == skip.resolve():
            continue
        rel = str(path.relative_to(search_root))
        for first_line, src in _code_pieces(path):
            if not any(n in src for n in names):
                continue
            for line, value in scan_source(src, names):
                cands.append(Candidate(value, f"{rel}:{first_line + line - 1}", _is_test(path.relative_to(search_root))))
    if not cands:
        return RunLength(None, "no caller of the document with a numeric run length was found", [])
    tiers = [("scripts", [c for c in cands if not c.is_test and not c.where.split(":")[0].endswith(".md")]),
             ("documentation", [c for c in cands if not c.is_test]),
             ("tests", cands)]
    kind, pool = next((k, c) for k, c in tiers if c)               # code that runs, then text snippets, then tests
    counts = Counter(c.value for c in pool)
    best = max(counts.values())
    value = next(c.value for c in pool if counts[c.value] == best)       # first in file order among the most frequent
    distinct = sorted({c.value for c in cands})
    why = f"{counts[value]} of {len(pool)} calls in {kind} (first at {next(c.where for c in pool if c.value == value)})"
    if len(distinct) > 1:
        why += f"; callers use different values {distinct}, the most frequent in {kind} was taken"
    return RunLength(value, why, cands)
