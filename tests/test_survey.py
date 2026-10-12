import json
import subprocess

from pbg2sed2.survey import context_of, main, survey
from pathlib import Path

COMPOSITE = """name: demo
state:
  sim:
    _type: step
    address: local:TelluriumUTCStep
    config: {model_string: "A=1"}
    inputs: {}
    outputs: {result: [res]}
  res: {}
  emitter:
    _type: step
    address: local:RAMEmitter
    inputs: {result: [res]}
"""

PY = """
from process_bigraph import Composite
doc = {"state": {"p": {"_type": "process", "address": "local:Mystery", "interval": 0.5, "inputs": {}, "outputs": {}}}}
def go(sim, n):
    sim.run(10.0)
    sim.run(0)
    while n:
        sim.run(n)
class P:
    def calculate_timestep(self, interval, state):
        return interval
"""


def make_repo(root: Path) -> Path:
    repo = root / "demo-repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "demo.composite.yaml").write_text(COMPOSITE, encoding="ascii")
    (repo / "pkg" / "copy.composite.yaml").write_text(COMPOSITE, encoding="ascii")  # exact duplicate content
    (repo / "pkg" / "code.py").write_text(PY, encoding="ascii")
    (repo / "data.yaml").write_text("a: 1\n", encoding="ascii")
    (repo / "LICENSE").write_text("MIT License\n", encoding="ascii")
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    return repo


def test_context_of():
    assert context_of(Path("tests/test_x.py"), "python-literal") == "test"
    assert context_of(Path("pkg/a.composite.yaml"), "composite-file") == "composite-file"
    assert context_of(Path("spatio/_snapshots/a.json"), "composite-file") == "generated"
    assert context_of(Path("notebooks/a.ipynb"), "notebook-literal") == "notebook"


def test_survey_outputs_and_counts(tmp_path):
    repo = make_repo(tmp_path)
    out = tmp_path / "out"
    assert main(["--repo", str(repo), "--out", str(out)]) == 0
    for name in ("manifest.json", "inventory.jsonl", "drivers.json", "clock-usage.json", "gaps.json", "SURVEY.md"):
        text = (out / name).read_text(encoding="ascii")  # ASCII only
        assert text
    rows = [json.loads(x) for x in (out / "inventory.jsonl").read_text().splitlines()]
    assert len(rows) == 3
    tiers = sorted(r["tier"] for r in rows)
    assert tiers == ["A", "A", "E"]
    assert sum(1 for r in rows if r["duplicate_of"]) == 1
    usage = json.loads((out / "clock-usage.json").read_text())
    d = usage["authored"]["drivers"]
    assert d["run_calls"] == 3 and d["run_zero"] == 1 and d["inside_while"] == 1
    assert [o["class"] for o in d["calculate_timestep_overrides"]] == ["P"]
    gaps = json.loads((out / "gaps.json").read_text())
    assert any(g["key"] == "opaque:Mystery" for g in gaps["rows"])
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["repositories"][0]["license_files"] == ["LICENSE"]


def test_survey_is_deterministic(tmp_path):
    repo = make_repo(tmp_path)
    a, b = tmp_path / "a", tmp_path / "b"
    survey([repo], a)
    survey([repo], b)
    assert (a / "inventory.jsonl").read_text() == (b / "inventory.jsonl").read_text()


def test_no_repositories_is_an_error(tmp_path):
    assert main(["--out", str(tmp_path / "o")]) == 12
