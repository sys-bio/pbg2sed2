# Formats and layout (phase R0)

This file fixes the formats the survey and the importer write, so that every later phase reads the same shapes.  They are version 0: they change only with a note here.

## Layout

```
src/pbg2sed2/
  reader.py        static loader: composite files, bundles, Python and notebook literals, templates (never imports foreign code)
  classify.py      node roles from known_classes.json, provisional tier of a document
  clock.py         the clock-usage record of a document (see process-bigraph-clock.md, section 8)
  drivers.py       run(...) calls and calculate_timestep overrides found in Python files (ast)
  survey.py        the survey: discovery, inventory, manifest, gap ledger, SURVEY.md
  known_classes.json   recognition table (class name -> role, SED2 element); versions are recorded, not enforced
scripts/pbg_survey.py  command line wrapper of survey.py
tests/                 synthetic documents; no test needs a surveyed repository or work/
docs/formats.md        this file
work/                  git-ignored: todo/, others/, survey/<date>/ (generated), INDEX.md
```

The importer is `mapping.py` (document to SED2 and report), `model.py` (the model the wrapper loads), `emit.py` (validation with libsed2, writing), `cli.py` (the `pbg2sed2` command), `callers.py` (the run length from callers) and `verify.py` with `corpus.py` (verification and corpus fetch).  The package uses libsed2 and does not depend on pySED2Translate, and the forward translator does not depend on this package (item T-7): the two mapping tables are separate, and the back-translation to Process Bigraph, run in CI by `tests/test_corpus_verification.py`, is what shows drift between them.

## Survey output (`pbg_survey.py --out DIR`)

* `manifest.json`: `tool`, `version`, `date`, `repositories` (name, commit, commit date, remote, licence files and the first line of the first, `cloned_from_session`), `files_read`, `notes` (files that parsed but held no document, unreadable files), `studies_seen` (study.yaml files are counted, not parsed), `repos_without_documents`.
* `inventory.jsonl`: one JSON object per extracted document or fragment: `id` (`repo:path[#entry|:line]`), `repo`, `source`, `form` (`composite-file`, `bundle-entry`, `python-literal`, `notebook-literal`, `template-file`), `context` (`composite-file`, `source`, `docs`, `notebook`, `test`, `generated`), `shape`, `content_hash`, `duplicate_of`, `tier` (A, B, C, D, E, none, template, fragment), `tier_reasons`, `opaque_classes`, `coupled`, `shared_stores`, `nodes`, `inventory`, `clock`.
* `drivers.json`: per Python file, the `run(...)` calls (argument kind, `run(0)`, `force_complete`, enclosing loop kinds) and the `calculate_timestep` overrides.  The scan is approximate (it looks at files that mention process_bigraph or Composite and skips obvious non-simulation receivers).
* `clock-usage.json`: counts over the clock records for authored documents, test documents and generated documents, with up to five example ids each, and the driver counts.
* `gaps.json`: gap ledger v0, machine-written: `key`, `construct`, `category` (task, data type, model language, output, run semantics, out of scope), `why_sed2_cannot_say_it`, `nearest_sed2_element`, `documents`, `repositories`, `example`.  Curated later.
* `SURVEY.md`: generated from the files above; never edited by hand.

Documents are counted once: fragments (a single node dict) and exact duplicates (same normalized state) are excluded from the counts.  Test and generated documents are shown beside the authored ones and are not used for the clock-usage evidence.

## Tiers (provisional)

A: known simulator node(s) and no coupling through shared stores.  B: stores, declarative steps and stateful utilities only.  C: contains classes of the forward translator.  D: a coupled, spatial or agent model class, or simulators or opaque classes sharing stores with other working nodes.  E: opaque classes, no coupling found.  `none`: no process or step, or only drawing nodes.  `template`: a template file (sites are not interpreted).  These are labels with reasons, from static reading; they decide the order of work, not a translation.

## Import report (version 0, written by `pbg2sed2`)

JSON with the keys `source`, `tier`, `status` (`translatable` or `not-translatable`), `reasons` (why a document is not translatable), `notes` (facts about the translation the reader must know, for example that the original restarts its integrator at every interval), `mapped`, `dropped` (nodes that are not translated; the document is then not translatable: it is translated whole or not at all), `unsupported` (constructs with no SED2 equivalent) and `columns` (the report's columns in order, used by the verification) and `run_length` (for a document that runs in ticks: `value`, `source` saying where the number came from, and every `candidates` found). Each entry of the three lists has `path` (the node path in the document), `class` and `what` (the reason or the SED2 element). Exit statuses: 0 written, 10 unreadable, 11 not translatable (reasons printed and in the report), 12 other error (including a SED2 document that libsed2 rejects, or libsed2 missing: nothing is written unvalidated).

## Verification (phase R4)

`scripts/pbg_verify.py DOC [--duration T] [--param NAME=VALUE] --backend roadrunner --backend copasi` runs the original document with process-bigraph (this executes the document's classes, so it needs an environment prepared for the document) and the generated SED2 through pysed2translate and each backend, and compares the data: a row of the original is matched to the SED2 row of the same time and every column both have is compared with |a - e| <= abs + rel * |e| (defaults 1e-6 and 1e-4), where e is the original's value. Columns only the original has fail the comparison; the original's empty t = 0 row (the stores are filled by the first update) is dropped and counted; SED2 rows without an original are counted. The original is run in a core built with the registration function of the wrapper package the document uses (viva-tellurium, viva-copasi), as that package's own loader does. Columns the original keys by another label (COPASI fluxes by reaction name) are renamed to the SBML ids; rows of a process without a time port get the time `i * interval`. `--param` gives the value of a `${NAME}` parameter that has no default, or overrides one (viva-copasi's loader supplies `model_dir` itself, so its documents need `--param model_dir=<composites directory>`). A difference is reported with its size and is never tuned away. The result is printed as JSON and, with `--json PATH`, also written to PATH; a program that reads it (the tests) uses the file, because packages imported while running the original may print to stdout.

### Run length (`constants:duration`)

A document does not say how long to run (`Composite.run(T)` does).  The SED2 document gets a top-level constant `duration` and the time range ends at `#constants:duration` (`start` 0, `interval` the process interval).  The value is, in order: the `--duration` option; the number a script that calls the document passes to `run(...)`, found by `callers.py` under `--search-root` (default: the document's directory; Python files, notebooks and fenced code in Markdown; the call must be in the same function or cell as the call that names the document; scripts are preferred to Markdown snippets, those to tests; the most frequent value wins, ties go to the first in file order, and the report lists every candidate and says when they differ); otherwise 1.  `run_length.source` in the report says which, and a `notes` entry says when the default 1 was taken.

### Back-translation (a test, not part of the translation)

`scripts/pbg_verify.py DOC --via pbg --backend roadrunner` writes the SED2, translates it back to a Process Bigraph composite with `pysed2translate-pbg` (simulation in the host runtime), runs that composite and compares its report with the original document's data, as for the generated script.  It needs `pysed2translate-pbg`, which only the tests and this script use; the package `pbg2sed2` never imports it.  CI runs these tests in the `roundtrip` job (`PBG2SED2_REQUIRE_FULL` set, so a missing package fails instead of skipping).

## Corpus

`corpus/manifest.json` (tracked) lists the documents that tests read: `id` (`repo:file`), `org`, `repo`, `path`, `ref` (a full commit id) and `sha256`. The files themselves are not committed: `pbg2sed2.corpus.ensure(id)` returns the path in `corpus-cache/` (git-ignored; override with `PBG2SED2_CORPUS`) and downloads `https://raw.githubusercontent.com/<org>/<repo>/<ref>/<path>` when the file is missing. A file whose content differs from the recorded sha256 is rejected, whether it was just downloaded or was already there. For the survey, `pbg_survey.py --repos-dir DIR --repo-list repos-p1.json --repo-list repos-p2.json --fetch` reads GitHub's API listing of the organisation (saved by hand; see T-3), takes the repositories that are neither archived nor forks, shallow-clones the ones missing from `DIR` (skipping those larger than `--max-mb`, default 400) and surveys them. To add a document to the corpus, add its entry with the commit and sha256 of the content at that commit.

## Decisions taken in R0 and what is deferred

Taken without asking (the plan's own assumptions, or forced by the work): documents are read statically; the survey writes its output outside the repository's tracked files; antimony models are converted to SBML at import (the user's answer to plan question 5); counts exclude duplicates and fragments; intervals are compared in exact decimal arithmetic.  Asked of the user and since answered: where the corpus lives (T-2), how the organisation's repository list is built (T-3), the place of the SED2 proposal file (T-4), partial translation (T-5, decided against: a document is translated whole or not at all), the run length when a document gives none (T-6) and where the importer and the shared mapping table live (T-7).
