"""Run the originals and the translations (phase R4).  These tests execute the documents' own classes, so they run only
where process_bigraph, the wrapper packages, pysed2translate and libsed2 are installed.

Each document is verified in its own interpreter (scripts/pbg_verify.py): a COPASI step run after a Tellurium step in the
same interpreter crashes it on Linux (draft W-13 of the forward translator's notes; the maintainers' answer: roadrunner, python-copasi
and python-libsbml each link their own libSBML statically, so the one loaded first wins the shared symbols; fixed on their main only
for the UTC step, not for the steady-state step and the UTC process), and a verification run should not depend on what ran before it."""

import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


def need(mod):
    """Import `mod`, or skip the module's tests.  With PBG2SED2_REQUIRE_FULL set (the full CI job) a missing package is an error: the tests must not pass by being skipped."""
    if os.environ.get("PBG2SED2_REQUIRE_FULL"):
        importlib.import_module(mod)
    else:
        pytest.importorskip(mod)


for mod in ("process_bigraph", "viva_tellurium", "viva_copasi", "pysed2translate", "libsed2", "libsbml", "antimony"):
    need(mod)

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "pbg_verify.py"


def check(corpus_doc, entry_id, tmp_path, backends, duration=None, via="script"):
    copasi = entry_id.startswith("viva-copasi")
    if copasi:
        corpus_doc("viva-copasi:repressilator.xml")
    path = corpus_doc(entry_id)
    cmd = [sys.executable, str(SCRIPT), str(path), "--out", str(tmp_path), "--via", via]
    if copasi:
        cmd += ["--param", f"model_dir={path.parent}"]
    if duration is not None:
        cmd += ["--duration", str(duration)]
    for b in backends:
        cmd += ["--backend", b]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError:
        pytest.fail(f"no result from the verification (exit {p.returncode}): {(p.stdout + p.stderr)[-600:]}")


def assert_agree(result):
    assert result["backends"]
    for backend, comparison in result["backends"].items():
        assert "error" not in comparison, comparison
        assert comparison["ok"], (backend, comparison["max_abs"], comparison["worst"], comparison["notes"])


@pytest.mark.parametrize("backend", ["roadrunner", "copasi"])
def test_tellurium_decay_demo_agrees(corpus_doc, tmp_path, backend):
    assert_agree(check(corpus_doc, "viva-tellurium:decay-demo.composite.yaml", tmp_path, [backend], 3.0))


def test_tellurium_steady_state_agrees(corpus_doc, tmp_path):
    assert_agree(check(corpus_doc, "viva-tellurium:steady-state.composite.yaml", tmp_path, ["roadrunner", "copasi"]))


def test_copasi_utc_step_agrees(corpus_doc, tmp_path):
    assert_agree(check(corpus_doc, "viva-copasi:utc-step.composite.yaml", tmp_path, ["roadrunner", "copasi"]))


def test_copasi_steady_state_agrees(corpus_doc, tmp_path):
    assert_agree(check(corpus_doc, "viva-copasi:steady-state.composite.yaml", tmp_path, ["roadrunner", "copasi"]))


@pytest.mark.xfail(strict=True, reason="the original is wrong: CopasiUTCProcess returns absolute values that the store adds (draft O-1); remove the mark when viva-copasi is fixed")
def test_copasi_utc_process_agrees(corpus_doc, tmp_path):
    assert_agree(check(corpus_doc, "viva-copasi:utc-process.composite.yaml", tmp_path, ["copasi"], 3.0))


# The back-translation: the SED2 that pbg2sed2 wrote is translated back to a process-bigraph composite by
# pysed2translate-pbg, that composite is run, and its data is compared with the original document's.  This is a test of
# the two translators together.  Neither depends on the other: the package pbg2sed2 never imports the forward translator,
# which is only needed here (it is installed in CI).
need("pysed2translate_pbg")


@pytest.mark.parametrize("backend", ["roadrunner", "copasi"])
def test_back_translation_tellurium_decay_demo(corpus_doc, tmp_path, backend):
    assert_agree(check(corpus_doc, "viva-tellurium:decay-demo.composite.yaml", tmp_path, [backend], 3.0, via="pbg"))


def test_back_translation_tellurium_steady_state(corpus_doc, tmp_path):
    assert_agree(check(corpus_doc, "viva-tellurium:steady-state.composite.yaml", tmp_path, ["roadrunner"], via="pbg"))


def test_back_translation_copasi_utc_step(corpus_doc, tmp_path):
    assert_agree(check(corpus_doc, "viva-copasi:utc-step.composite.yaml", tmp_path, ["roadrunner", "copasi"], via="pbg"))


def test_back_translation_copasi_steady_state(corpus_doc, tmp_path):
    assert_agree(check(corpus_doc, "viva-copasi:steady-state.composite.yaml", tmp_path, ["copasi"], via="pbg"))
