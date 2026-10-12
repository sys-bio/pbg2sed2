"""Repository-level clock evidence that a document cannot show: `run(...)` drivers and `calculate_timestep` overrides.

Static (ast) and approximate: a `.run(x)` call is counted only in files that mention process_bigraph or Composite,
and calls on obvious non-simulation receivers (subprocess, asyncio, ...) are skipped.  The result is evidence for
the clock analysis, not a proof.
"""

from __future__ import annotations

import ast
from pathlib import Path

SKIP_RECEIVERS = {"subprocess", "asyncio", "loop", "pytest", "os", "ray", "nb", "runner", "app", "uvicorn", "client", "pool", "executor"}


def _arg_kind(node: ast.AST) -> str:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return "literal"
    if isinstance(node, (ast.Name, ast.Attribute)):
        return "named"
    if isinstance(node, ast.BinOp):
        return "expression"
    if isinstance(node, ast.Call):
        return "call"
    return "other"


class _V(ast.NodeVisitor):
    def __init__(self):
        self.calls = []
        self.overrides = []
        self._ctx: list[str] = []
        self._cls: list[str] = []

    def visit_ClassDef(self, node):
        self._cls.append(node.name)
        self.generic_visit(node)
        self._cls.pop()

    def visit_FunctionDef(self, node):
        if node.name == "calculate_timestep" and self._cls:
            self.overrides.append({"class": self._cls[-1], "line": node.lineno})
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_While(self, node):
        self._ctx.append("while")
        self.generic_visit(node)
        self._ctx.pop()

    def visit_For(self, node):
        self._ctx.append("for")
        self.generic_visit(node)
        self._ctx.pop()

    def visit_Call(self, node):
        f = node.func
        if isinstance(f, ast.Attribute) and f.attr == "run" and 1 <= len(node.args) <= 2:
            recv = f.value
            rname = recv.id if isinstance(recv, ast.Name) else (recv.attr if isinstance(recv, ast.Attribute) else "")
            if rname not in SKIP_RECEIVERS:
                self.calls.append({"line": node.lineno, "arg": _arg_kind(node.args[0]),
                                   "zero": isinstance(node.args[0], ast.Constant) and node.args[0].value == 0,
                                   "force_complete": any(k.arg == "force_complete" for k in node.keywords) or len(node.args) == 2,
                                   "in_loop": list(dict.fromkeys(self._ctx))})
        self.generic_visit(node)


def scan_python_file(path: Path, label: str) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return None
    mentions = "process_bigraph" in text or "Composite" in text
    if not mentions and "calculate_timestep" not in text:
        return None
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    v = _V()
    v.visit(tree)
    if not mentions:
        v.calls = []
    if not v.calls and not v.overrides:
        return None
    return {"file": label, "run_calls": v.calls, "calculate_timestep_overrides": v.overrides}
