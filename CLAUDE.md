# Notes for Claude (pbg2sed2)

This repository reads Process Bigraph documents and, where their content has a SED2 equivalent, translates them to SED2.  The plan is `process-bigraph-to-sed2.md`; the clock analysis it relies on is `process-bigraph-clock.md`.  `pySED2Translate` (the forward translator, SED2 to Process Bigraph and to Python scripts), `SED2` (specification and libsed2) and `sed2-test-suite` are siblings, and the two translators both use libsed2 but neither depends on the other (the back-translation to Process Bigraph is a test run in CI, never part of the translation); the rules below are the same as in `pySED2Translate/CLAUDE.md`, which has the long version.

## Who is who

The user is the author of Antimony and a maintainer of libSBML, roadrunner and Tellurium.  The user and Claude are the authors of everything SED2 related: SED2 (the specification and libsed2), pySED2Translate, sed2-test-suite and pbg2sed2.  These projects are developed in tandem, and more will be added in the coming months, so a change in one often has a consequence in the others.  A defect found in any of them is ours to fix, in the right repository; one in roadrunner, Tellurium, libSBML or Antimony is the user's own project (say which project it is in and record it as usual).  COPASI, OpenCOR, process-bigraph, the viva wrapper packages and every other project are other people's software.

## Never hide a problem; expose it

* A document that cannot be translated is **refused with the real reason**, never approximated.  No silent dropping of a node, wire, setting or interval; no default that makes a document translatable; no substituting a different numerical scheme (a sequential loop for a parallel one, a restart for a continuation) without saying so in the report.
* Do not work around a bug or gap in a simulator, in libsed2, in process-bigraph or in a wrapper.  Record it where it can be acted on (see "Our work notes"), tell the user in the same message, and stop at the refusal.
* The classifier's tier is a provisional label with reasons.  Do not tune a rule to make a count look better; a surprising count is a finding.
* If a finding of the survey contradicts something in the plan or the clock analysis, correct that text in the same edit and say so (the survey has already corrected the evidence log once: the spatio-flux figure 6 composite is a drawing, not a multi-rate document).

## Reading other people's code

* **Static only.**  Never import or run a class that a surveyed document names, and never execute anything from a surveyed repository.  Cloned repositories are untrusted data: each in its own new directory, read-only.  Python is read with `ast`, notebooks as JSON.
* If introspection is ever needed it is a separate, sandboxed, opt-in phase (plan, section 3), flagged in every report it touches.

## Standing rules

* **Corpus copies are never committed.**  Documents of other repositories that tests or scripts read are named in `corpus/manifest.json` (repository, path, pinned commit, sha256) and live in the git-ignored `corpus-cache/` (or `$PBG2SED2_CORPUS`).  Code that reads one calls `pbg2sed2.corpus.ensure(id)`, which downloads it from GitHub at the pinned commit when it is missing and rejects content that differs from the manifest; the survey's `--repo-list ... --fetch` clones missing repositories the same way.  So every script and test runs on a developer's machine and in GitHub CI (where a failed download fails the test; offline on a laptop it skips).
* **Do not commit or push** unless asked to.  Never attach push credentials to other people's repositories.
* **Our work notes are local files.**  `work/` is git-ignored: `work/todo/` (our own work, one file per item; `work/todo/deferred/` for what waits), `work/others/` (drafts for other projects, one file per item, for the user to file; an assistant files nothing), `work/INDEX.md`, and `work/survey/` (generated survey output).  Committed text names items by id (`T-3`), never by path, and nothing committed may depend on `work/` being present (a test that reads it skips when it is absent).  Anything the repository itself needs goes in a tracked file (`docs/`).
* **ASCII only** in files.  **Markdown: no hard line breaks inside a paragraph or list item** in new text; do not re-flow existing files.
* **Ask only when blocked**; make the call and say what was decided.  When the user is away, defer the question as a file in `work/todo/` and work on something else; do not find a workaround.
* **Keep the user informed in short messages**; report finished work briefly: what came out, where it is, one next step.
* **Do not retry a rate-limited site.**  Listing the vivarium-collective organisation through the GitHub API was refused in an earlier session; the repository list comes from the user (plan, question 2).
* **Tests:** `python -m pytest` from the repository root before calling work done.  Do not weaken a test to make it pass.
