import json
import shutil
from pathlib import Path

import pytest

pytest.importorskip("libsbml")
pytest.importorskip("antimony")
pytest.importorskip("libsed2")

from pbg2sed2.cli import main  # noqa: E402

DOC = """name: d
state:
  sim:
    _type: step
    address: "local:TelluriumSteadyStateStep"
    config:
      model: |
        model m
          S1 = 10; S2 = 0
          S1 -> S2; k*S1; k = 0.3
          S2 -> ; k2*S2; k2 = 0.1
        end
    inputs: {}
    outputs:
      steady_state_concentrations: [c]
  c: {}
  em:
    _type: step
    address: "local:RAMEmitter"
    config:
      emit:
        c: "map[float]"
    inputs:
      c: [c]
"""


def test_cli_writes_validated_sed2_model_and_report(tmp_path, capsys):
    src = tmp_path / "d.composite.yaml"
    src.write_text(DOC)
    out = tmp_path / "o" / "d.sed2.json"
    assert main([str(src), "--out", str(out), "--report", str(tmp_path / "o" / "d.import.json")]) == 0
    sed2 = json.loads(out.read_text())
    assert sed2["tasks"]["s"]["_type"] == "steadyState"
    assert (tmp_path / "o" / "d.model.sbml").exists()
    rep = json.loads((tmp_path / "o" / "d.import.json").read_text())
    assert rep["status"] == "translatable" and rep["columns"] == ["S1", "S2"]


def test_cli_exit_codes(tmp_path, capsys):
    src = tmp_path / "d.composite.yaml"
    src.write_text(DOC.replace("TelluriumSteadyStateStep", "SomeUnknownStep"))
    assert main([str(src), "--out", str(tmp_path / "x.sed2.json")]) == 11
    assert not (tmp_path / "x.sed2.json").exists()
    assert main([str(tmp_path / "missing.yaml"), "--out", str(tmp_path / "y.sed2.json")]) == 10
