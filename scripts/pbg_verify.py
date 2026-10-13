#!/usr/bin/env python3
"""Translate a document and compare the original's data with the SED2's (phase R4).  RUNS foreign code: use an environment prepared for the document."""
import argparse
import contextlib
import csv
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from pbg2sed2.classify import classify  # noqa: E402
from pbg2sed2.cli import parse_params, run_length_finder  # noqa: E402
from pbg2sed2.emit import write_result  # noqa: E402
from pbg2sed2.mapping import Options, translate  # noqa: E402
from pbg2sed2.reader import load_path  # noqa: E402
from pbg2sed2.verify import read_report, verify  # noqa: E402


def run_via_pbg(sed2_path: Path, backend: str):
    """The back-translation: SED2 to a process-bigraph composite (pysed2translate-pbg, simulation in the host runtime), run it, read its report.

    This is test tooling.  pbg2sed2 does not depend on pysed2translate-pbg; this script is run in CI where it is installed.
    """
    with tempfile.TemporaryDirectory() as tmp:
        doc, res = Path(tmp) / "b.pbg.composite.json", Path(tmp) / "out"
        main_ = "import sys; from pysed2translate_pbg.cli import main; raise SystemExit(main(sys.argv[1:]))"
        for cmd in (["translate", str(sed2_path), "--backend", backend, "--wrappers", "off", "-o", str(doc)],
                    ["run", str(doc), "--input-dir", str(sed2_path.parent.resolve()), "--output-dir", str(res)]):
            p = subprocess.run([sys.executable, "-c", main_, *cmd], capture_output=True, text=True)
            if p.returncode != 0:
                raise RuntimeError(f"pysed2translate-pbg {cmd[0]} exit {p.returncode}: {(p.stdout + p.stderr).strip()[-400:]}")
        reports = sorted(res.glob("*.r.csv"))
        if len(reports) != 1:
            raise RuntimeError(f"expected one report, found {[r.name for r in reports]}")
        with open(reports[0], newline="", encoding="utf-8") as fh:
            return read_report(list(csv.reader(fh)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("doc", type=Path)
    ap.add_argument("--select")
    ap.add_argument("--duration", type=float, help="run length for a process-based document (also used to run the original)")
    ap.add_argument("--backend", action="append", default=[])
    ap.add_argument("--out", type=Path, help="keep the generated SED2 here (default: a temporary directory)")
    ap.add_argument("--via", choices=["script", "pbg"], default="script",
                    help="how the SED2 is run: the generated script (default) or the back-translation to a process-bigraph composite")
    ap.add_argument("--json", type=Path, help="also write the result here; a program that reads the result should use this, as imported packages may print to stdout")
    ap.add_argument("--abs-tol", type=float, default=1e-6)
    ap.add_argument("--rel-tol", type=float, default=1e-4)
    ap.add_argument("--search-root", type=Path, help="where to look for scripts that call the document")
    ap.add_argument("--param", action="append", default=[], metavar="NAME=VALUE")
    a = ap.parse_args()
    docs, _ = load_path(a.doc, a.doc.name, parse_params(a.param))
    if a.select:
        docs = [d for d in docs if a.select in d.source]
    if len(docs) != 1:
        print(f"{len(docs)} documents; use --select", file=sys.stderr)
        return 12
    doc = docs[0]
    outdir = a.out or Path(tempfile.mkdtemp())
    out = outdir / (a.doc.name.split(".")[0] + ".sed2.json")
    res = translate(doc, classify(doc), Options(name=out.name.removesuffix(".sed2.json"), duration=a.duration, base_dir=a.doc.resolve().parent, find_run_length=run_length_finder(a.doc, a.search_root)))
    code = write_result(res, out, outdir / (out.name.removesuffix(".sed2.json") + ".import.json"))
    if code != 0:
        print(f"not translated (exit {code}): {res.reasons}")
        return code
    run_time = res.run_length["value"] if res.kind == "process-ticks" and res.run_length else 0.0
    # The originals' packages print to stdout when they are imported (for example "skipping `x` (missing optional dep ...)"); the result must be the only thing on stdout.
    with contextlib.redirect_stdout(sys.stderr):
        v = verify(doc, res, out, a.backend or ["roadrunner"], run_time, a.abs_tol, a.rel_tol, runner=run_via_pbg if a.via == "pbg" else None)
    text = json.dumps(v, indent=1, default=str)
    if a.json:
        a.json.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if all(b.get("ok") for b in v["backends"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
