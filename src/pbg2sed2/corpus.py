"""The corpus of documents that tests and scripts read.

Copies of other people's documents are never committed.  `corpus/manifest.json` (tracked) names each document by
repository, path and a pinned commit, with the sha256 of the content; the files live in the git-ignored directory
`corpus-cache/` (or the directory in the environment variable PBG2SED2_CORPUS).  `ensure` returns the local path and
downloads the file from GitHub first when it is not there, so the same code runs on a developer's machine and in CI.
A downloaded file whose sha256 differs from the manifest is rejected, never used.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "corpus" / "manifest.json"


class CorpusError(Exception):
    """A document could not be obtained (offline, not found, or its content differs from the manifest)."""


def cache_dir() -> Path:
    return Path(os.environ.get("PBG2SED2_CORPUS") or ROOT / "corpus-cache")


def entries() -> dict[str, dict]:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {e["id"]: e for e in data["entries"]}


def url(entry: dict) -> str:
    return f"https://raw.githubusercontent.com/{entry['org']}/{entry['repo']}/{entry['ref']}/{entry['path']}"


def local_path(entry: dict) -> Path:
    return cache_dir() / entry["repo"] / entry["path"]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def ensure(entry_id: str, timeout: float = 60.0) -> Path:
    """The local path of a corpus document; downloaded first when missing."""
    entry = entries()[entry_id]
    path = local_path(entry)
    if path.exists():
        if _sha(path.read_bytes()) != entry["sha256"]:
            raise CorpusError(f"{path} exists but its content differs from the manifest (sha256); delete it to fetch it again")
        return path
    try:
        with urllib.request.urlopen(url(entry), timeout=timeout) as resp:
            data = resp.read()
    except (urllib.error.URLError, OSError) as exc:
        raise CorpusError(f"cannot download {url(entry)}: {exc}") from exc
    if _sha(data) != entry["sha256"]:
        raise CorpusError(f"{url(entry)}: downloaded content differs from the manifest (sha256)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def ensure_repo(repo: str, dest: Path, org: str = "vivarium-collective", depth: int = 1, timeout: float = 600.0) -> Path:
    """A shallow clone of a repository in `dest/repo`, made when it is not there (for the survey)."""
    target = dest / repo
    if target.exists():
        return target
    if shutil.which("git") is None:
        raise CorpusError("git is not installed; cannot clone " + repo)
    dest.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["git", "clone", "--depth", str(depth), "-q", f"https://github.com/{org}/{repo}.git", str(target)],
                       capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        shutil.rmtree(target, ignore_errors=True)
        raise CorpusError(f"git clone of {org}/{repo} failed: {r.stderr.strip()[:200]}")
    return target
