"""pbg2sed2 DOC --out NNNNN.sed2.json --report NNNNN.import.json

Exit status: 0 written, 10 unreadable, 11 not translatable (reasons printed and in the report), 12 other error.
A document is translated whole or not at all: a part with no translation makes it not translatable (exit 11).
"""

from __future__ import annotations

import argparse
import sys

import yaml
from pathlib import Path

from .callers import document_names, find_run_length
from .classify import classify
from .emit import EXIT_ERROR, EXIT_UNREADABLE, write_result
from .mapping import Options, translate
from .reader import load_path


def parse_params(items: list[str]) -> dict:
    out: dict = {}
    for it in items:
        name, eq, text = it.partition("=")
        if not eq or not name:
            raise ValueError(f"--param expects NAME=VALUE, got {it!r}")
        out[name] = yaml.safe_load(text)
    return out


def run_length_finder(doc_path: Path, search_root: Path | None = None):
    """A function that looks for scripts that call the document with a run length."""
    root = search_root
    if root is None:
        root = doc_path.resolve().parent
        for p in [root, *root.parents]:
            if (p / ".git").exists():
                root = p
                break

    def find(doc):
        names = document_names(str(doc.header.get("name") or ""), doc_path.name)
        return find_run_length(root, names, skip=doc_path)
    return find


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="pbg2sed2", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("doc", type=Path, help="a composite file, a bundle, a Python file or a notebook with document literals")
    ap.add_argument("--out", type=Path, required=True, help="the SED2 document to write (model files go beside it)")
    ap.add_argument("--report", type=Path, help="the import report (JSON)")
    ap.add_argument("--select", help="when the file holds several documents, the one whose source contains this text")
    ap.add_argument("--duration", type=float, help="run length of a process-based document; without it the header's default_n_steps, then a script that calls the document, then 1 is used (written to constants:duration)")
    ap.add_argument("--search-root", type=Path, help="where to look for scripts that call the document (default: the git repository that holds it, else its directory)")
    ap.add_argument("--base-dir", type=Path, help="directory against which relative model files are resolved (default: the document's directory)")
    ap.add_argument("--param", action="append", default=[], metavar="NAME=VALUE",
                    help="a value for a ${NAME} parameter (wins over the header's default; the value is read as YAML, so 10 is a number)")
    a = ap.parse_args(argv)
    try:
        overrides = parse_params(a.param)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_ERROR
    try:
        docs, notes = load_path(a.doc, a.doc.name, overrides)
    except Exception as exc:  # unreadable input
        print(f"cannot read {a.doc}: {exc}", file=sys.stderr)
        return EXIT_UNREADABLE
    if not docs:
        print(f"{a.doc}: no document found ({'; '.join(notes) or 'nothing recognisable'})", file=sys.stderr)
        return EXIT_UNREADABLE
    if a.select:
        docs = [d for d in docs if a.select in d.source]
    if len(docs) != 1:
        print(f"{len(docs)} documents match; choose one with --select:\n  " + "\n  ".join(d.source for d in docs[:20]), file=sys.stderr)
        return EXIT_ERROR
    doc = docs[0]
    opts = Options(name=a.out.name.removesuffix(".sed2.json").removesuffix(".json"), duration=a.duration,
                   base_dir=a.base_dir or a.doc.resolve().parent, find_run_length=run_length_finder(a.doc, a.search_root))
    result = translate(doc, classify(doc), opts)
    code = write_result(result, a.out, a.report)
    print(f"{doc.source}: {result.status}" + ("" if not result.reasons else ": " + "; ".join(result.reasons)))
    for e in result.dropped + result.unsupported:
        print(f"  not translated: {e.path} ({e.cls}): {e.what}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
