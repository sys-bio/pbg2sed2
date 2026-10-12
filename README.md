# pbg2sed2

A translator of process bigraph files to SED2.

Status: early.  What exists is the static reader, a provisional classifier, a corpus survey (phases R0 to R2 of the plan), an importer for the viva-tellurium and viva-copasi wrapper classes (`pbg2sed2 DOC --out FILE.sed2.json`) and a verification harness that runs the original and the SED2 and compares the data (phases R3 and R4, tier A only).

* `process-bigraph-to-sed2.md`: the plan (phases, gap ledger, verification, the SED2 proposal topics).
* `process-bigraph-clock.md`: what SED2 cannot say about process-bigraph's clock, proposals P1 to P5, and the evidence log.
* `docs/formats.md`: layout, survey output formats, tiers, decisions.
* `CLAUDE.md`: working rules.

The reader and the survey read documents statically and never import or run anything from a surveyed repository; only the verification runs the original document's classes.

```
pip install -e .[dev]
python -m pytest
python scripts/pbg_survey.py --repos-dir PATH_TO_CLONES --out OUT_DIR
pbg2sed2 DOC --out OUT.sed2.json --report OUT.import.json [--duration T] [--search-root DIR] [--param NAME=VALUE]
python scripts/pbg_verify.py DOC [--duration T] --backend roadrunner --backend copasi   # runs the original: use a prepared environment
python scripts/pbg_verify.py DOC --via pbg --backend roadrunner   # the back-translation to Process Bigraph (needs pysed2translate-pbg; a test tool, not part of the translation)
```
