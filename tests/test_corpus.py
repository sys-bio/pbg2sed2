import json
import urllib.error

import pytest

from pbg2sed2 import corpus
from pbg2sed2.survey import main as survey_main

DATA = b"name: x\nstate: {}\n"
ENTRY = {"id": "r:x.yaml", "org": "o", "repo": "r", "path": "d/x.yaml", "ref": "abc", "sha256": corpus._sha(DATA)}


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setenv("PBG2SED2_CORPUS", str(tmp_path / "cache"))
    monkeypatch.setattr(corpus, "entries", lambda: {ENTRY["id"]: ENTRY})
    return tmp_path / "cache"


class Resp:
    def __init__(self, data):
        self.data = data

    def read(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_url_is_pinned_to_the_commit():
    assert corpus.url(ENTRY) == "https://raw.githubusercontent.com/o/r/abc/d/x.yaml"


def test_existing_file_is_used_without_download(cache, monkeypatch):
    (cache / "r" / "d").mkdir(parents=True)
    (cache / "r" / "d" / "x.yaml").write_bytes(DATA)
    monkeypatch.setattr(corpus.urllib.request, "urlopen", lambda *a, **k: pytest.fail("downloaded"))
    assert corpus.ensure("r:x.yaml").read_bytes() == DATA


def test_missing_file_is_downloaded_once(cache, monkeypatch):
    calls = []
    monkeypatch.setattr(corpus.urllib.request, "urlopen", lambda u, timeout=0: calls.append(u) or Resp(DATA))
    p = corpus.ensure("r:x.yaml")
    assert p.read_bytes() == DATA and calls == [corpus.url(ENTRY)]
    corpus.ensure("r:x.yaml")
    assert len(calls) == 1


def test_changed_content_is_rejected_both_ways(cache, monkeypatch):
    monkeypatch.setattr(corpus.urllib.request, "urlopen", lambda u, timeout=0: Resp(b"other"))
    with pytest.raises(corpus.CorpusError, match="differs"):
        corpus.ensure("r:x.yaml")
    assert not (cache / "r" / "d" / "x.yaml").exists()
    (cache / "r" / "d").mkdir(parents=True)
    (cache / "r" / "d" / "x.yaml").write_bytes(b"edited")
    with pytest.raises(corpus.CorpusError, match="differs"):
        corpus.ensure("r:x.yaml")


def test_offline_is_a_corpus_error(cache, monkeypatch):
    def boom(*a, **k):
        raise urllib.error.URLError("no network")
    monkeypatch.setattr(corpus.urllib.request, "urlopen", boom)
    with pytest.raises(corpus.CorpusError, match="cannot download"):
        corpus.ensure("r:x.yaml")


def test_manifest_entries_are_complete_and_pinned():
    for e in json.loads(corpus.MANIFEST.read_text())["entries"]:
        assert len(e["ref"]) == 40 and len(e["sha256"]) == 64 and e["id"].startswith(e["repo"] + ":")


def test_survey_takes_the_in_scope_repositories_of_a_listing(tmp_path):
    repos = tmp_path / "clones"
    for name in ("keep", "archived"):
        (repos / name / ".git").mkdir(parents=True)
        (repos / name / "a.composite.yaml").write_text("state:\n  p:\n    _type: process\n    address: 'local:Foo'\n")
    listing = tmp_path / "p1.json"
    listing.write_text(json.dumps([{"name": "keep", "archived": False, "fork": False, "size": 10},
                                   {"name": "archived", "archived": True, "fork": False, "size": 10}]))
    out = tmp_path / "out"
    assert survey_main(["--repos-dir", str(repos), "--repo-list", str(listing), "--out", str(out)]) == 0
    manifest = json.loads((out / "manifest.json").read_text())
    assert [r["name"] for r in manifest["repositories"]] == ["keep"]
