import importlib
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def need(mod):
    """Import `mod`, or skip the tests that need it.  With PBG2SED2_REQUIRE_FULL set (the full CI job) a missing package is an error:
    the tests must not pass by being skipped."""
    if os.environ.get("PBG2SED2_REQUIRE_FULL"):
        return importlib.import_module(mod)
    return pytest.importorskip(mod)


@pytest.fixture(scope="session")
def corpus_doc():
    """Local path of a corpus document, downloaded from GitHub at its pinned commit when it is not in the cache.

    Offline on a developer's machine the test is skipped; in CI (CI is set) a failed download fails the test."""
    from pbg2sed2 import corpus

    def get(entry_id: str) -> Path:
        try:
            return corpus.ensure(entry_id)
        except corpus.CorpusError as exc:
            if os.environ.get("CI"):
                raise
            pytest.skip(f"corpus document not available: {exc}")

    return get
