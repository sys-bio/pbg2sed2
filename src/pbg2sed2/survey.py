"""Corpus survey (phase R1): discover documents in cloned repositories, extract and normalize them, inventory them.

Reads files only.  Never imports or executes anything from a surveyed repository.  Writes, into --out:
  manifest.json     repositories (commit, licence file), files read, counts, notes, errors
  inventory.jsonl   one line per extracted document: classification, inventory, clock-usage record
  drivers.json      run(...) calls and calculate_timestep overrides found in the repositories' Python files
  clock-usage.json  counts over the clock-usage records (feeds the evidence log of the clock analysis)
  gaps.json         gap ledger v0 (machine-written; curated later)
  SURVEY.md         generated from the files above; never edited by hand
"""

from __future__ import annotations

import argparse
import collections
import datetime
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from . import __version__, corpus
from .classify import classify
from .clock import clock_record
from .drivers import scan_python_file
from .reader import Document, COMPOSITE_SUFFIXES, TEMPLATE_SUFFIXES, load_path

SKIP_DIRS = {".git", "build", "dist", "node_modules", "venv", ".venv", "__pycache__", "site-packages", ".tox", ".mypy_cache", ".pytest_cache"}
MAX_BYTES = 5_000_000
MODEL_KEYS = ("model_file", "model_source", "model_string", "model_path", "model_id", "biomodel_id", "sbml", "antimony", "model")


def _git(repo: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception:
        return ""


def repo_entry(repo: Path) -> dict:
    lic = sorted(p.name for p in repo.iterdir() if p.is_file() and p.name.upper().startswith(("LICENSE", "LICENCE", "COPYING")))
    first = ""
    if lic:
        try:
            first = (repo / lic[0]).read_text(encoding="utf-8", errors="replace").strip().splitlines()[0][:80]
        except Exception:
            first = ""
    return {"name": repo.name, "commit": _git(repo, "rev-parse", "HEAD"), "commit_date": _git(repo, "log", "-1", "--format=%cs"),
            "remote": _git(repo, "config", "--get", "remote.origin.url"), "license_files": lic, "license_first_line": first,
            "cloned_from_session": True}


def walk_files(repo: Path):
    for p in sorted(repo.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(repo)
        if any(part in SKIP_DIRS or part.endswith(".egg-info") for part in rel.parts):
            continue
        yield p, rel


def wants(p: Path) -> bool:
    n = p.name.lower()
    if n.endswith((".py", ".ipynb")):
        return True
    if n.endswith((".json", ".yaml", ".yml")):
        return True
    return False


def prefilter(p: Path, rel: Path) -> bool:
    """Cheap text test so that ordinary JSON and YAML (data, configs) are not parsed as documents."""
    n = p.name.lower()
    if n.endswith(COMPOSITE_SUFFIXES + TEMPLATE_SUFFIXES):
        return True
    try:
        if p.stat().st_size > MAX_BYTES:
            return False
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False
    return "_type" in text and ("process" in text or "step" in text)


def context_of(rel: Path, form: str) -> str:
    """Where a document sits: authored examples and composite files count differently from tests and generated dumps."""
    parts = [x.lower() for x in rel.parts]
    name = parts[-1]
    if any(x in ("_snapshots", "reports", "out", "outputs", "results", "composite-resolve") for x in parts):
        return "generated"
    if "tests" in parts or "test" in parts or name.startswith("test_") or name.endswith("_test.py") or name == "tests.py" or name == "conftest.py":
        return "test"
    if name.endswith(".ipynb") or "notebooks" in parts:
        return "notebook"
    if "docs" in parts or "doc" in parts:
        return "docs"
    if form in ("composite-file", "bundle-entry", "template-file"):
        return "composite-file"
    return "source"


def content_hash(doc: Document) -> str:
    blob = json.dumps(doc.state, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def inventory(doc: Document, cls) -> dict:
    kinds = collections.Counter(n.kind for n in cls.nodes)
    addresses = collections.Counter(n.address for n in cls.nodes)
    cfg_keys = collections.defaultdict(set)
    model_refs = set()
    for n in cls.nodes:
        cfg_keys[n.cls or n.address].update(k for k in n.config if not str(k).startswith("_"))
        model_refs.update(k for k in n.config if k in MODEL_KEYS)
    types = collections.Counter()

    def walk(v):
        if isinstance(v, dict):
            t = v.get("_type")
            if isinstance(t, str) and t not in ("process", "step"):
                types[t] += 1
            for k, x in v.items():
                if not (isinstance(k, str) and k.startswith("_") and k != "_value"):
                    walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)

    walk(doc.state)
    return {
        "node_kinds": dict(kinds), "addresses": dict(addresses), "roles": cls.roles,
        "config_keys": {k: sorted(v) for k, v in cfg_keys.items()},
        "other_types": dict(types), "model_reference_keys": sorted(model_refs),
        "nested_nodes": sum(1 for n in cls.nodes if n.nested),
        "bridge": bool(doc.header.get("bridge")) or "bridge" in doc.state,
        "emitters": sorted({n.cls for n in cls.nodes if n.role == "emitter"}),
        "resolved_placeholders": doc.resolved, "unresolved_placeholders": doc.unresolved,
        "complete": doc.complete, "unresolved_expressions": doc.unresolved_exprs[:5],
    }


def survey(repos: list[Path], out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    manifest = {"tool": "pbg2sed2-survey", "version": __version__, "date": datetime.date.today().isoformat(),
                "repositories": [], "files_read": 0, "notes": [], "errors": []}
    lines = []
    drivers = []
    studies = []
    repo_docs = collections.Counter()
    seen_hash: dict[str, str] = {}
    for repo in repos:
        entry = repo_entry(repo)
        manifest["repositories"].append(entry)
        for p, rel in walk_files(repo):
            label = f"{repo.name}/{rel.as_posix()}"
            if p.name == "study.yaml":
                studies.append(label)
                continue
            if p.suffix == ".py":
                d = scan_python_file(p, label)
                if d:
                    d["context"] = context_of(rel, "python")
                    drivers.append(d)
            if not wants(p) or not prefilter(p, rel):
                continue
            manifest["files_read"] += 1
            docs, notes = load_path(p, label)
            for n in notes:
                manifest["notes"].append({"file": label, "note": n})
            for doc in docs:
                cls = classify(doc)
                h = content_hash(doc)
                rec = {"id": f"{repo.name}:{doc.source.split('/', 1)[1] if '/' in doc.source else doc.source}", "repo": repo.name,
                       "source": doc.source, "form": doc.form, "context": context_of(rel, doc.form), "header_name": doc.header.get("name"),
                       "shape": doc.shape, "content_hash": h, "duplicate_of": seen_hash.get(h),
                       "tier": cls.tier, "tier_reasons": cls.reasons, "opaque_classes": cls.opaque_classes,
                       "coupled": cls.coupled, "shared_stores": cls.shared_stores,
                       "nodes": [n.to_json() for n in cls.nodes],
                       "inventory": inventory(doc, cls), "clock": clock_record(doc, cls)}
                seen_hash.setdefault(h, rec["id"])
                lines.append(rec)
                if cls.tier != "fragment" and rec["duplicate_of"] is None:
                    repo_docs[repo.name] += 1
    manifest["studies_seen"] = len(studies)
    manifest["repos_without_documents"] = [r["name"] for r in manifest["repositories"] if repo_docs[r["name"]] == 0]
    (out / "inventory.jsonl").write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in lines), encoding="ascii")
    (out / "drivers.json").write_text(json.dumps(drivers, indent=1, sort_keys=True), encoding="ascii")
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="ascii")
    usage = {"authored": clock_usage(lines, [d for d in drivers if d["context"] != "test"], AUTHORED),
             "tests": clock_usage(lines, [d for d in drivers if d["context"] == "test"], ("test",)),
             "generated": clock_usage(lines, [], ("generated",))}
    (out / "clock-usage.json").write_text(json.dumps(usage, indent=1, sort_keys=True), encoding="ascii")
    gaps = gap_ledger(lines)
    (out / "gaps.json").write_text(json.dumps(gaps, indent=1, sort_keys=True), encoding="ascii")
    (out / "SURVEY.md").write_text(survey_md(manifest, lines, usage, gaps, drivers, studies), encoding="ascii", errors="replace")
    return {"documents": len(lines), "repositories": len(repos)}


def _real(lines):
    """Documents that count: not fragments, not duplicates of an earlier document."""
    return [r for r in lines if r["tier"] != "fragment" and r["duplicate_of"] is None]


AUTHORED = ("composite-file", "source", "docs", "notebook")


def clock_usage(lines: list[dict], drivers: list[dict], contexts: tuple = AUTHORED) -> dict:
    docs = [r for r in _real(lines) if r["context"] in contexts]
    sim = [r for r in docs if r["tier"] not in ("none", "template")]
    c = collections.Counter()
    ex = collections.defaultdict(list)

    def hit(key, r):
        c[key] += 1
        if len(ex[key]) < 5:
            ex[key].append(r["id"])

    for r in sim:
        k = r["clock"]
        hit("interval:" + k["interval_kind"], r)
        if k["intervals_defaulted"]:
            hit("interval_defaulted", r)
        if k["step_wired_to_process_interval"]:
            hit("step_wired_to_process_interval", r)
        if k["nodes_reading_an_interval"]:
            hit("node_reads_an_interval", r)
        if k["nodes_reading_global_time"]:
            hit("node_reads_global_time", r)
        if k["hidden_state_classes_known"]:
            hit("hidden_state_class_known", r)
        if k["classes_with_unknown_state"]:
            hit("classes_with_unknown_state", r)
        if k["time_windows"]:
            hit("time_window_or_gate", r)
        if k["shared_stores_between_processes"]:
            hit("processes_sharing_a_store", r)
        if k["structural_sentinels"]:
            hit("structural_sentinels", r)
        if k["steps_without_process_upstream"]:
            hit("steps_without_process_upstream", r)
        if k["parallel_processes_flag"]:
            hit("parallel_processes_flag", r)
        hit("run_length:" + k["run_length_in_document"], r)
    calls = [(d["file"], x) for d in drivers for x in d["run_calls"]]
    arg = collections.Counter(x["arg"] for _, x in calls)
    return {"contexts": list(contexts), "documents_considered": len(sim), "counts": dict(sorted(c.items())), "examples": dict(ex),
            "drivers": {"run_calls": len(calls), "by_argument": dict(arg), "run_zero": sum(1 for _, x in calls if x["zero"]),
                        "with_force_complete": sum(1 for _, x in calls if x["force_complete"]),
                        "inside_while": sum(1 for _, x in calls if "while" in x["in_loop"]),
                        "inside_for": sum(1 for _, x in calls if "for" in x["in_loop"]),
                        "calculate_timestep_overrides": [{"file": d["file"], **o} for d in drivers for o in d["calculate_timestep_overrides"]]}}


def gap_ledger(lines: list[dict]) -> dict:
    docs = _real(lines)
    rows: dict[str, dict] = {}

    def row(key, construct, category, why, nearest):
        r = rows.setdefault(key, {"construct": construct, "category": category, "why_sed2_cannot_say_it": why,
                                  "nearest_sed2_element": nearest, "documents": 0, "repositories": set(), "example": None})
        return r

    for r in docs:
        if r["tier"] in ("none", "template", "C"):
            continue
        seen = set()
        for cname in r["opaque_classes"]:
            k = "opaque:" + cname
            if k in seen:
                continue
            seen.add(k)
            g = row(k, f"opaque class {cname}", "task", "the class is not in the recognition table; its behaviour is in Python", "unknown")
            g["documents"] += 1
            g["repositories"].add(r["repo"])
            g["example"] = g["example"] or r["id"]
        for n in r["nodes"]:
            if n["role"] == "coupled-model":
                k = "coupled-model:" + n["class"]
                if k in seen:
                    continue
                seen.add(k)
                g = row(k, f"coupled, spatial or agent model class {n['class']}", "task",
                        "a model class whose behaviour is spatial, particle-based or coupled; no SED2 task describes it", "none")
                g["documents"] += 1
                g["repositories"].add(r["repo"])
                g["example"] = g["example"] or r["id"]
        k = r["clock"]
        for key, cond, construct, cat, why, near in [
            ("clock:common-grid", k["interval_kind"] == "common-grid", "processes whose intervals have no integer ratio (a common tick exists)", "run semantics", "a Loop has one range (clock proposal P2: range step = the common tick, `every` counts)", "none"),
            ("clock:integer-multiples", k["interval_kind"] == "integer-multiples", "processes with different intervals that are integer multiples", "run semantics", "a Loop has one range (clock proposal P2; nested loops by hand)", "Loop nested in Loop"),
            ("clock:step-to-interval", bool(k["step_wired_to_process_interval"]), "a Step that sets a process's interval", "run semantics", "ranges are fixed before the run (clock proposals P3 and P4)", "OneStepStochasticSimulation"),
            ("clock:time-window", bool(k["time_windows"]), "a time-gated process (window)", "run semantics", "no per-sub-task window (clock proposal P2)", "Loop plus ModelChange"),
            ("clock:structural", k["structural_sentinels"] > 0, "dynamic structure (_add, _remove, _divide)", "run semantics", "static task graph and result shapes (clock gap G6)", "none"),
        ]:
            if cond:
                g = row(key, construct, cat, why, near)
                g["documents"] += 1
                g["repositories"].add(r["repo"])
                g["example"] = g["example"] or r["id"]
        if r["coupled"] and r["tier"] == "D":
            g = row("coupling", "simulator or model nodes coupled through shared stores", "run semantics",
                    "SED2 runs tasks and passes whole results; simultaneous coupling needs sibling sub-tasks and a merge (clock gap G2)", "Loop with sibling sub-tasks")
            g["documents"] += 1
            g["repositories"].add(r["repo"])
            g["example"] = g["example"] or r["id"]
        for e in r["inventory"]["emitters"]:
            if e != "RAMEmitter" and e != "ram-emitter":
                g = row("emitter:" + e, f"emitter {e}", "output", "a storage choice SED2 does not model", "report")
                g["documents"] += 1
                g["repositories"].add(r["repo"])
                g["example"] = g["example"] or r["id"]
    out = []
    for key, g in sorted(rows.items(), key=lambda kv: (-kv[1]["documents"], kv[0])):
        g = dict(g)
        g["key"] = key
        g["repositories"] = sorted(g["repositories"])
        out.append(g)
    return {"status": "v0: machine-written from the pilot survey; curate before use", "rows": out}


def survey_md(manifest, lines, usage, gaps, drivers, studies) -> str:
    docs = _real(lines)
    dup = len(lines) - len(docs) - sum(1 for r in lines if r["tier"] == "fragment" and r["duplicate_of"] is None)
    tiers = collections.Counter(r["tier"] for r in docs)
    forms = collections.Counter(r["form"] for r in docs)
    per_repo = collections.Counter(r["repo"] for r in docs)
    addr = collections.Counter()
    for r in docs:
        for a, n in r["inventory"]["addresses"].items():
            addr[a] += n
    out = []
    w = out.append
    w("# Survey of Process Bigraph documents (generated)")
    w("")
    w(f"Generated {manifest['date']} by pbg2sed2-survey {manifest['version']}.  This file is written by the tool from `inventory.jsonl`, `drivers.json`, `clock-usage.json` and `gaps.json`; do not edit it by hand.  The tiers are provisional labels with reasons (plan, section 2), from static reading only.")
    w("")
    w("## Scope")
    w("")
    w(f"{len(manifest['repositories'])} repositories, {manifest['files_read']} files parsed, {len(lines)} documents or fragments extracted, of which {len(docs)} distinct documents (fragments and exact duplicates removed from the counts below; {dup} duplicates, {sum(1 for r in lines if r['tier'] == 'fragment')} fragments).  {len(studies)} `study.yaml` files were seen and not parsed (they reference composites).")
    w("")
    w("| Repository | Commit | Date | Licence file | Documents |")
    w("|---|---|---|---|---|")
    for e in manifest["repositories"]:
        w(f"| {e['name']} | {e['commit'][:7]} | {e['commit_date']} | {', '.join(e['license_files']) or 'none'} ({e['license_first_line']}) | {per_repo[e['name']]} |")
    w("")
    w("## Documents by tier")
    w("")
    w("| Tier | Documents |")
    w("|---|---|")
    for t, n in sorted(tiers.items()):
        w(f"| {t} | {n} |")
    w("")
    w("## Documents by context")
    w("")
    w("Authored: composite files, document literals in source, docs and notebooks.  Test: literals in test files.  Generated: snapshots and run reports written by the projects' own tools.  Only the authored documents are used for the clock-usage table below; the test and generated rows are given beside it.")
    w("")
    w("| Context | Documents | Tier A | B | C | D | E | none |")
    w("|---|---|---|---|---|---|---|---|")
    for ctx in ("composite-file", "source", "docs", "notebook", "test", "generated"):
        sub = [r for r in docs if r["context"] == ctx]
        tc = collections.Counter(r["tier"] for r in sub)
        w(f"| {ctx} | {len(sub)} | {tc['A']} | {tc['B']} | {tc['C']} | {tc['D']} | {tc['E']} | {tc['none']} |")
    w("")
    w("## Documents by source form")
    w("")
    w("| Form | Documents |")
    w("|---|---|")
    for t, n in sorted(forms.items()):
        w(f"| {t} | {n} |")
    incomplete = sum(1 for r in docs if not r["inventory"]["complete"])
    w("")
    w(f"Python and notebook literals with non-literal expressions (incomplete): {incomplete}.")
    w("")
    w("## Most frequent addresses")
    w("")
    w("| Address | Nodes |")
    w("|---|---|")
    for a, n in addr.most_common(25):
        w(f"| {a or '(none)'} | {n} |")
    w("")
    w("## Clock usage")
    w("")
    ua, ut, ug = usage["authored"], usage["tests"], usage["generated"]
    w(f"Authored documents with at least one node: {ua['documents_considered']} (tests: {ut['documents_considered']}; generated: {ug['documents_considered']}).  Examples are authored document ids.")
    w("")
    w("| Item | Authored | Tests | Generated | Examples (authored) |")
    w("|---|---|---|---|---|")
    keys = sorted(set(ua["counts"]) | set(ut["counts"]) | set(ug["counts"]))
    for k in keys:
        w(f"| {k} | {ua['counts'].get(k, 0)} | {ut['counts'].get(k, 0)} | {ug['counts'].get(k, 0)} | {', '.join(ua['examples'].get(k, [])[:3])} |")
    w("")
    w("Run drivers (Python files that mention process_bigraph or Composite; approximate):")
    w("")
    w("| Files | `run(...)` calls | By argument | `run(0)` | With force_complete | Inside while | Inside for | `calculate_timestep` overrides |")
    w("|---|---|---|---|---|---|---|---|")
    for label, u in (("not tests", ua), ("tests", ut)):
        d = u["drivers"]
        w(f"| {label} | {d['run_calls']} | {d['by_argument']} | {d['run_zero']} | {d['with_force_complete']} | {d['inside_while']} | {d['inside_for']} | {len(d['calculate_timestep_overrides'])} |")
    for label, u in (("not tests", ua), ("tests", ut)):
        for o in u["drivers"]["calculate_timestep_overrides"][:10]:
            w(f"* ({label}) `{o['class']}` in {o['file']}:{o['line']}")
    w("")
    w("## Gap ledger v0 (top rows)")
    w("")
    w("| Construct | Category | Documents | Repositories | Example |")
    w("|---|---|---|---|---|")
    for g in gaps["rows"][:25]:
        w(f"| {g['construct']} | {g['category']} | {g['documents']} | {', '.join(g['repositories'])} | {g['example']} |")
    w("")
    w("## Repositories without extractable documents")
    w("")
    w(", ".join(manifest["repos_without_documents"]) or "none")
    w("")
    if manifest["notes"]:
        w("## Reader notes")
        w("")
        for n in manifest["notes"][:30]:
            w(f"* {n['file']}: {n['note']}")
        w("")
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repos-dir", type=Path, help="directory whose subdirectories are cloned repositories")
    ap.add_argument("--repo", type=Path, action="append", default=[], help="one cloned repository (repeatable)")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--repo-list", type=Path, action="append", default=[], metavar="JSON",
                    help="a page of GitHub's API listing of the organisation (repeatable); with --fetch the in-scope repositories "
                         "(not archived, not forks) that are not in --repos-dir are cloned there (depth 1)")
    ap.add_argument("--fetch", action="store_true", help="clone the in-scope repositories of --repo-list that are missing from --repos-dir")
    ap.add_argument("--max-mb", type=int, default=400, help="with --fetch, skip repositories larger than this (as GitHub reports it)")
    a = ap.parse_args(argv)
    repos = list(a.repo)
    if a.repo_list:
        if not a.repos_dir:
            print("--repo-list needs --repos-dir", file=sys.stderr)
            return 12
        listing = [r for f in a.repo_list for r in json.loads(f.read_text(encoding="utf-8"))]
        scope = sorted({r["name"] for r in listing if not r["archived"] and not r["fork"] and r["name"] != ".github"})
        sizes = {r["name"]: r["size"] // 1024 for r in listing}
        for name in scope:
            if (a.repos_dir / name).exists() or not a.fetch:
                continue
            if sizes[name] > a.max_mb:
                print(f"skipped {name}: {sizes[name]} MB", file=sys.stderr)
                continue
            try:
                corpus.ensure_repo(name, a.repos_dir)
            except corpus.CorpusError as exc:
                print(f"not fetched {name}: {exc}", file=sys.stderr)
        repos += [a.repos_dir / n for n in scope if (a.repos_dir / n / ".git").exists()]
        a.repos_dir = None
    if a.repos_dir:
        repos += sorted(p for p in a.repos_dir.iterdir() if p.is_dir() and (p / ".git").exists())
    if not repos:
        print("no repositories given", file=sys.stderr)
        return 12
    res = survey(repos, a.out)
    print(json.dumps(res))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
