# Translating Process Bigraph to SED2

Location: this file moved here from pySED2Translate on 2026-10-10 (the translator repository is `pbg2sed2`).  Names without a repository, such as `process-bigraph.md`, `build.md`, `CLAUDE.md`, `docs/deferred.md` and `docs/libsed2-api-notes.md`, are files of `pySED2Translate`; `work/` is this repository's git-ignored work directory.

Status: a plan.  No survey, code or SED2 proposal has been written.  This is the reverse companion of
`process-bigraph.md` (SED2 to Process Bigraph); the two share a mapping table and a test harness, see section 7.
Written 2026-10-08; pointer to the clock analysis added 2026-10-09; the clock evidence track (sections 4.1, 4.3 and 8) added the same day.  Facts about process-bigraph come from the research recorded in that file (version 1.8.5,
git e5325c1) plus the small check described in section 4.1.

## 1. Goals and what "success" means

1. **An importer**, `pbg2sed2`: read a Process Bigraph document and write a valid SED2 document when its content has a
   SED2 equivalent.  Where it does not, say exactly what, instead of producing a plausible approximation.
2. **A corpus survey**: find the process-bigraph documents that exist in the vivarium GitHub projects, normalize them,
   and count what they contain.  The survey is a result in itself and drives everything else.
3. **A gap analysis**: list the things process-bigraph models do that SED2 cannot say, ranked by how often they occur,
   and turn the most important into a proposal file in the SED2 repository describing tasks (processes) that SED2
   might add.

Success is not "convert as many documents as possible".  Following CLAUDE.md, a document is in exactly one of three
classes, and the importer says which, with reasons:

| Class | Meaning | Output |
|---|---|---|
| Translatable | Every node has a SED2 equivalent | A valid SED2 document |
| (Partly translatable) | A core experiment can be extracted, but named parts cannot | **Not done (decided 2026-10-10):** such a document is Not translatable; the report lists every part that has no translation. A later test of SED2 namespaces may carry the parts in `pbg@` tasks (SED2's TODO.md, low priority) |
| Not translatable | The behaviour is in code or in coupling SED2 cannot express | No SED2; a report with the reasons (these feed the gap ledger) |

A SED2 document that the importer writes must pass libsed2 validation, run on the backends the capability table
allows, and agree with running the original document (section 6).  Anything else is a bug or a recorded disagreement.

## 2. Why the reverse is a different kind of problem

SED2 describes an experiment on a model: which model, which simulation, which outputs.  A process-bigraph document is
a *program*: a wiring of Python classes that are looked up by name and carry their own behaviour.  So:

* The forward direction is total on the supported subset of SED2.  The reverse is partial by nature.
* The meaning of a node is in the class named by its `address`, not in the JSON.  The JSON for a `TelluriumProcess`
  says nothing about what it does; knowing the class does.  The importer therefore recognizes nodes by a **table of
  known classes** (package, class name, version range), and treats every other address as opaque.
* A document does not say how long to run.  The run length is the argument of `Composite.run(T)`, the
  `--steps` option of `process_bigraph.run_composite`, or a spec's `default_n_steps`.  SED2 needs an end time.
* A document may not carry its model.  Wrappers take an Antimony string inline, an SBML file path relative to the
  working directory, or a URL.
* Process-bigraph is built for coupling: several processes advance together and exchange state through shared stores.
  SED2 runs independent tasks and passes whole results between them.  This is the largest conceptual gap and probably
  the main finding of the gap analysis.

Documents fall into tiers that decide how hard the job is:

| Tier | What it is | Expected outcome |
|---|---|---|
| A | One or more known SBML/Antimony simulator nodes (viva-tellurium, viva-copasi) with their emitters | Mostly translatable: modelImport, simulation, report |
| B | Stores and declarative math/calculation steps, with emitters | Translatable to constants and calculations, if the step classes are known |
| C | Documents produced by this project's own forward translator (`pysed2translate.pbg`) | Exactly invertible; our best test, and it needs no external corpus |
| D | Several coupled models, spatial, agent-based, or multiscale composites (the bulk of the ecosystem, judging by repository names) | Not translatable; feeds the gap ledger |
| E | Custom Python processes, generators that need code to run, anything opaque | Not translatable; counted, not analysed |

## 3. Reading documents safely

The corpus is other people's code.  Building a `Composite` imports and runs the classes a document names, so:

* **Static first.**  The reader parses JSON/YAML and never imports a process class.  Addresses are matched against the
  known-class table by name.  This is the default and the only mode in the first phases.
* **Introspection later, sandboxed, opt-in.**  Reading a class's ports (`inputs()` / `outputs()`) would improve
  classification but needs importing the package.  If it is ever done: a separate environment per repository, pinned
  to a commit, no network, and clearly flagged in the report.  The `git:` address protocol in process-bigraph already
  isolates foreign code this way; reusing it is an option to evaluate, not to assume.
* Cloned repositories are untrusted data: each goes into its own new directory and is read, not executed.

Source forms to handle, in the order they will be added:

1. `*.composite.json|yaml|yml`: the repository's own convention.  Header fields `name`, `description`, `requires`,
   `parameters` (with `${name}` placeholders and defaults), then `state`.  The importer resolves placeholders to their
   defaults and records that it did.
2. Saved documents (`Composite.save`, bundles) and `*.template.*` files with unfilled "sites" (holes).  A document with
   an open site is not runnable and is classified "not translatable: template".
3. Document literals inside Python and notebooks (`{'_type': 'process', 'address': ...}`), found by pattern or by Python's
   `ast` module.  Many are built from helper functions (`make_tellurium_document(...)`, `emitter_from_wires(...)`), which
   a static reader cannot evaluate without running them.  First pass: extract only literals; record the rest.
4. Generators (`@composite_generator`): code that builds a document.  Needs execution; phase R7, sandboxed, optional.

## 4. The corpus survey

### 4.1 What is already known

* process-bigraph's own design note (docs/superpowers/specs/2026-06-28-composite-spec-unified-declaration-design.md)
  says an audit covered "93 `*.composite.{yaml,json}` files across ~20 pbg-* repos", 13 `@composite_generator`
  generators in v2ecoli, and about 12 `study.yaml` files.  It names the repositories (autopoiesis, bioreactordesign,
  membrane-actin, tyssue, copasi, tellurium, smoldyn, martini, comets, mem3dg, cellpack, yalla, biomodels, nfsim,
  readdy, medyan, lammps, compucell3d, parsimony, caspule).  Most are not SBML simulators, which already predicts that
  tier D is the majority.
* A quick count in the three clones I have (process-bigraph, viva-tellurium, viva-copasi): 6 standalone composite
  files (3 + 3), but about 30 files containing document literals in Python or notebooks.  So many documents live in
  code, and a survey that reads only `*.composite.*` files will undercount.
* The `pbg-*` repositories were renamed `viva-*`, with import shims (`pbg_tellurium` redirects to `viva_tellurium`).
  Recognition must accept both names.
* The paper's Supplement 1 (read 2026-10-09) shows the canonical JSON as a `schema` tree plus a `state` tree with
  `stores` and `processes` sub-trees; the 1.8.5 documents examined here are one `state` tree whose nodes carry `_type`.
  The importer must expect both shapes (whether 1.8.5 loads the supplement's shape is untested).  Supplement 2 and the
  Spatio-Flux repository are a ready corpus of real composites (metabolic, field, particle processes, `DynamicFBA` with
  COBRApy); add it to the survey list.  Everything here is subordinate to the modularity rule of
  `process-bigraph.md`, 3.11: the reverse direction is its own package.
* A first corpus already exists and was read on 2026-10-09: `process-bigraph/scripts/corpus/legacy_documents.json` (68 documents, 77 `interval` keys), plus the Python-built composites of cdFBA, crm-fba, spatio-flux and the viva-* repositories.  What it shows about the clock (one interval per document except three commensurate mixes; no `calculate_timestep`, no structural sentinels in the corpus; time-window interventions; a Step that reads the interval; a Step that sets a process's interval; no run-until driver) is the evidence log of `process-bigraph-clock.md`, section 8.  R1 extends that log with counts over the full survey; it does not start from nothing.

### 4.2 Enumeration, and a constraint found while researching

Listing the organisation's repositories through the GitHub API was **refused in this session** (organisation endpoints
and GraphQL are blocked; the session is bound to named repositories).  Cloning a named public repository and fetching
its web page both worked.  So the list has to come from one of:

* the user's own machine (`gh repo list vivarium-collective --limit 300`), saved as a file this plan reads;
* a seed list assembled by hand from the names above plus the organisation's web page, repository by repository;
* attaching repositories to the session one at a time.

Open question 2 asks which.  Whatever is chosen, the list is stored as part of the corpus manifest so the survey can be
repeated.  Do not retry anything that answers 429 (CLAUDE.md).

### 4.3 Procedure (phase R1, no translation)

1. Build the repository list (including archived and forked repositories, marked as such).  Decide the scope beyond
   `vivarium-collective`: for example `CovertLab/vEcoli`, which builds on process-bigraph (question 2).
2. For each repository: shallow clone into a new directory, record the commit SHA and the licence file, and never
   execute anything.
3. Find candidates: `*.composite.*`, `*.template.*`, `study.yaml`, saved bundles, notebooks and Python files matching
   `'_type'`/`"_type"` with `process` or `step`, `composite_generator`, `Composite(`, `emitter_from_wires`.
4. Extract each document into a normalized form: JSON, parameters resolved to defaults, with a manifest entry
   (repository, SHA, path, source form, licence, how it was extracted).
5. Inventory each document with a script: node counts by kind; the address histogram; port types; emitters used; config
   keys by class; intervals; nesting and bridges; sites; whether there is a model reference; which tier it is; and the clock-usage items of `process-bigraph-clock.md`, section 8, "What to record per document" (intervals and whether they are commensurate in exact decimal arithmetic, classes with hidden state, an overridden `calculate_timestep` or a Step wired to an `interval`, time windows, Steps that read the interval, shared stores and their types, structural sentinels and whether the candidates or a cap are known, the run driver).
6. Generate `SURVEY.md` from the inventory (never written by hand): counts per tier, top addresses, top config keys,
   and a table of the repositories with no extractable documents.

Deliverables of R1: the manifest, the normalized documents (or only hashes and extraction scripts where the licence
does not allow copying; question 1), `SURVEY.md`, the clock-usage table (it extends the evidence log of `process-bigraph-clock.md`, section 8), and gap ledger v0 (section 5.2).  R1 needs none of the forward
translator, so it can run alongside forward phases 0 and 1.

## 5. Importer design and the gap ledger

### 5.1 Pipeline

```
load  ->  normalize (resolve ${...}, unify yaml/json)  ->  classify nodes (known / opaque)  ->  tier the document
      ->  map (section 5.3)  ->  emit SED2 + report, or refuse with reasons
```

Command line: a separate program, `pbg2sed2 DOC --out NNNNN.sed2.json --report NNNNN.import.json`, because the direction
and inputs differ from `pysed2translate`.  Exit statuses mirror the forward program: 0 written, 10 unreadable, 11 not
translatable (reasons printed and in the report), 12 other error.  There is no exit status for a partial translation: a
document is translated whole or not at all (2026-10-10).  The report is JSON with three lists: mapped, dropped,
unsupported, each entry naming the node path and the reason.

### 5.2 The gap ledger

Every refusal and every dropped item is also a row in `gaps.json` (machine-written, curated later): the construct, how
many documents and repositories contain it, one example path, why SED2 cannot say it, the nearest SED2 element, a
candidate addition, and a category (task, data type, model language, output, run semantics, out of scope).  Keeping it
as data from the first run means the proposal file in section 6 is a curated view of evidence, not an opinion.
Working files of the survey (the ledger, a draft `SURVEY.md`, per-document notes) are items in `work/todo/` of this repository, listed in `work/INDEX.md`; they are git-ignored, and committed text names them by id.  Where the corpus itself lives is question 1.

### 5.3 Planned mapping (to be confirmed on real documents)

| Process-bigraph construct | SED2 | Notes |
|---|---|---|
| Plain store value never written by any node | `constants` | |
| Declarative math step (known class) | `calculation` | Expression syntax converted to SED2 math; unsupported functions refuse. |
| `TelluriumUTCStep`, `CopasiUTCStep` (start, end or time, n_points) | `modelImport` + `explicitODESimulation` + `report` | n_points versus numberOfSteps differ by one; test explicitly. COPASI wrapper starts at 0. |
| `TelluriumProcess`, `CopasiUTCProcess` with `interval` | `explicitODESimulation` with a uniform range | Only when the run length is known (section 2) and no other node is wired to the same stores. Otherwise tier D. |
| `TelluriumSteadyStateStep`, `CopasiSteadyStateStep` | `steadyState` | |
| `species_overrides`, `parameter_overrides` | `modelChange` `setValues` | |
| `integrator: cvode` and tolerances | KiSAO algorithm and tolerances of the simulation | `gillespie` is a stochastic task, deferred in SED2 tests. |
| `model_file`, `model_source` | `modelImport.location`, language SBML | Antimony inline: converted to SBML with libAntimony at import (decided, section 11). |
| `RAMEmitter` and similar, wired to some paths | `report` over references to the task outputs | Rows per tick become a time-course table; labels from port names. Other emitters (JSON, SQLite, Parquet) are storage choices SED2 does not model; recorded as a gap. |
| Declarative visualization steps | `plot2D` | Only where the data wired in is a simulation output. |
| Parameter sweeps inside a document (`RunProcess` and similar) | `parameterScan` / `loop` | Check against the actual classes in the corpus. |
| Anything wired between two simulator nodes, dynamic structure, spatial fields, agents | none | Gap ledger. |

### 5.4 Recognition table

`known_classes.json` maps (package, class, version range) to a handler.  It is the reverse of the forward translator's
table of step classes (section 7).  Both names of a renamed package are listed.  An address not in the table is opaque:
the node and everything wired only to it are reported as unsupported.

## 6. Verification

For every document the importer translates (not only tier C):

1. **Validate** the SED2 output with libsed2; refuse to write one with errors.
2. **Run the original** document with its original packages, in an environment prepared for that tier (heavy: COPASI,
   Tellurium; tier A only), and keep its emitter output.
3. **Run the SED2** through `pysed2translate` on every backend the capability table allows.
4. **Compare** with the suite's rules (|a-e| <= abs + rel*|e|, labels, shape).  The original's tolerances are mapped
   explicitly into the SED2, so differences are not hidden by defaults (CLAUDE.md: tolerances are set, not left
   alone).
5. A disagreement is analysed, not tuned away: is it the wrapper, the simulator, the importer, or a specification
   ambiguity?  Wrapper and simulator disagreements go to `sed2-test-suite/disagreements.json`; specification
   questions go to `SED2/TODO.md` (new section at the end); a draft of a report for the wrapper or simulator
   maintainers is one file in `work/others/` (index: `work/INDEX.md`; an assistant files nothing); an importer bug is
   fixed with a test that fails without the fix.  A reasonable first suspect list is the off-by-one in output points, the initial time, and COPASI/roadrunner
   default tolerances.

Note on names: "tier C" in this section is an *importer* test tier (our own forward output).  The forward plan's *test* tier C
(`process-bigraph.md`, section 7) is different: PBG-native documents whose expected data comes from a Python script
**translated** from the document.  The importer is route 1 for those scripts (PBG -> SED2 -> host script), which makes the
importer's output the oracle for the forward engine and the forward engine's output the check on the importer; a second,
smaller translator (a scheduler exporter) covers documents SED2 cannot express.  So the importer gains a customer before
the survey finishes.

Tier C (our own forward output) is invertible by construction, so `SED2 -> PBG -> SED2` must be the identity up to a
canonical form (ids, key order, defaults).  That test needs only the forward translator and runs in CI without any
external package, which makes it the first test the importer passes.

## 7. Parallels with the forward plan

| Forward (SED2 to PBG) | Reverse (PBG to SED2) | Shared |
|---|---|---|
| Phase 0: skeleton, runner | R0 and R1: decisions, survey | A manifest-and-golden-files habit |
| Step classes `pysed2translate.pbg.steps` | `known_classes.json` | **One mapping module**, `pbg/mapping.py`, from which both are generated or checked; a test fails if a step class has no reverse entry or the reverse names a class that does not exist |
| Capability table says which backend runs a task | Same table decides which imported tasks are runnable | `capabilities.json` unchanged |
| Golden PBG documents in `tests/golden/pbg/` | The same documents are the tier C inputs | One set of goldens, two directions |
| Exit status 11 = skip with reason | Exit status 11 = not translatable with reasons | Same reporting style |
| Gaps found go to SED2/TODO.md; reports about other projects are one file each in `work/others/` | Gaps found go to the ledger, then the proposal file; reports the same way | CLAUDE.md rules apply to both; `work/INDEX.md` indexes both |

Dependencies: R1 and R2 are independent of the forward work.  R3 needs the SED2 side of the capability table only.  R5 (tier C)
needs forward phase 2.

## 8. Phases

Each phase ends with passing tests and a short report to you; no phase starts before the one it depends on is green.

* **R0 - decisions and scaffolding.**  Answer the questions in section 11.  Fix the manifest format, the report format and the file
  layout.  No external access.
* **R1 - survey.**  Section 4.3.  Output: manifest, normalized documents, `SURVEY.md`, gap ledger v0.  Review point: do the numbers
  match the "mostly tier D" prediction?  This decides how much of R3 onward is worth doing.  Second review point, with the clock-usage table: re-test the clock proposals P1 to P5 against the counts (`process-bigraph-clock.md`, section 8), change the ones the counts show cannot work, and record the outcome in item T-5 of `SED2/work/todo/`.
* **R2 - reader.**  Static loader for `*.composite.*` with parameter resolution and node classification; tier assignment.  Tests on the
  six viva-tellurium and viva-copasi files and on synthetic documents for each tier.
* **R3 - importer for tiers A and B.**  Mapping of section 5.3, report (no partial translation).  Tests: a golden SED2 and report per input.
* **R4 - verification harness.**  Section 6, steps 2 to 5, on tier A.  First entries in the disagreement log if any.
* **R5 - round trip.**  Tier C, after forward phase 2.
* **R6 - proposal file.**  Curate the ledger into the SED2 proposal (section 9).  You review it before it is written into the SED2 repository.  The clock proposals enter it from the evidence log of `process-bigraph-clock.md`, section 8, after a last re-test, not from the first draft of that file.
* **R7 - optional.**  Document literals found by `ast`; generators in a sandbox.

**Standing track: the clock.**  Every document or repository read for this plan (in R1, and again in R2 and R3 whenever a new kind of document appears) is held against the clock proposals.  A finding that a proposal cannot express, or that makes it wrong, becomes a new row of the evidence log in `process-bigraph-clock.md` (section 8) naming the proposal it tests and the result, and the proposal is changed in the same edit.  The first pass (2026-10-09, ten application repositories and process-bigraph itself (corpus and tests)) already changed P2: it gained an active window, the step length, exact decimal arithmetic, and a corrected rule for what a sub-task that did not run contributes.  Nothing is proposed to `SED2/TODO.md` until the R1 counts exist (item T-5).

**Progress (2026-10-09, on your instruction to execute the plan).**  R0 is done and its questions are answered (section 11).  R1 and R2 are done on the eleven cloned repositories (`work/survey/2026-10-09-pilot/`).  R3 and R4 are done for the Tellurium and COPASI wrapper classes, tier A (the run length is `constants:duration`, from a calling script when one is found, else 1; the back-translation to Process Bigraph is a CI test): decay-demo, steady-state (both wrappers) and the COPASI utc-step translate and agree with the originals; the COPASI utc-process translates and the verification disagrees because the original is wrong (drafts O-1 and O-2 in `work/others/`); the OpenCOR documents are unblocked: libopencor, the package viva-opencor uses, works here (T-10), and the handlers are next.  R5 to R7 have not started; the clock track continues in `process-bigraph-clock.md`.  The record is `work/verification/2026-10-09-first-documents.md`.

Files as built (this repository; the first plan put the importer in pySED2Translate, which changed when this repository was created):

```
src/pbg2sed2/reader.py        # load, normalize, parameter resolution (--param overrides)
src/pbg2sed2/classify.py      # known/opaque nodes, tiers
src/pbg2sed2/known_classes.json
src/pbg2sed2/clock.py         # clock-usage record
src/pbg2sed2/survey.py        # R1: inventory, SURVEY.md, gap ledger v0
src/pbg2sed2/model.py         # models named by a document (Antimony to SBML, SBML element lists)
src/pbg2sed2/mapping.py       # handlers per wrapper class
src/pbg2sed2/emit.py          # libsed2 validation, writing, exit codes
src/pbg2sed2/cli.py           # pbg2sed2
src/pbg2sed2/verify.py        # R4: run the original and the SED2, compare
scripts/pbg_survey.py, scripts/pbg_verify.py
tests/
```

The corpus itself (manifest, normalized documents, SURVEY.md, gaps.json) does not belong in `src/`; the survey output is written under `work/survey/` (git-ignored); see question 1 (T-2).

## 9. The SED2 proposal file

A new file in the SED2 repository, name and folder to be chosen (suggestion: `SED2/proposals/process-bigraph-tasks.md`; a new section at the end of `SED2/TODO.md` is the alternative, as for every other proposal so far).  You and I are the authors of the SED2 repository, and the SED2 folder is connected now.  The file proposes, it does not specify: the specification, `SED2/Claude.md` and libsed2 change only when you decide.  Working items for it (the clock proposals, the checks below) are files in `SED2/work/todo/`, indexed in `SED2/work/INDEX.md`; the drafts and briefs about other projects are in `work/others/` of the repository they concern.

Each candidate entry will contain: a proposed task name; the purpose in SED2 terms; inputs and outputs as SED2 data (what
AnnotatedData shape comes out); parameters; what process-bigraph does today (one real example from the corpus, with the
repository and commit); which simulators could implement it; how it could be tested with an analytic result in the suite;
and the open questions.  Entries are ordered by corpus evidence (how many documents and repositories), then by how well
they fit SED2's task model (a task with inputs and outputs and no hidden state).  Items that do not fit (distributed
execution, caching, UI) go in a short "considered and left out" section so they are not rediscovered.

Candidate topics to test against the corpus.  These started as hypotheses from reading process-bigraph and its wrappers.  On 2026-10-09 each was checked against `SED2/SPECIFICATION.md` (the core sections and the class reference) and `SED2/TODO.md`.  Each item says what the specification has, what it lacks, and what the survey still has to find out.  Topics the specification already covers stay in the list as "covered", so that the survey classifies documents by them and does not propose them again.

1. **Coupled simulation (partly covered).**  Several models advancing together and exchanging state each interval.  The specification has `Loop` (iterations chained through `loopVariables`, one per element of a `range`; "a `Loop` always runs all of them and cannot end early"), `Scatter` (iterations that are independent of each other) and the common `Repeat` rule that the `subTasks` "may depend on each other".  So the narrowing found in `process-bigraph-clock.md` holds: sequential operator splitting on one clock is a `Loop` (the cosimulation template and sed2-test-suite case 00282 do it with an ODE and an FBA), and parallel coupling is sibling `subTasks` that read only the loop variables plus a `Calculation` that merges.  Not in the specification: several intervals on one timeline, a step that chooses its own next interval (ranges are fixed before the run), running until a condition, and a label for the coupling scheme.  Those are G1 to G5 and proposals P1 to P5 of the clock file, which are not yet in `TODO.md` (item T-5 in `SED2/work/todo/`).  The evidence review of 2026-10-09 (clock file, section 8) found commensurate multi-rate only (three documents), time windows (`Intervention`), a Step that needs the elapsed interval, a Step that sets a process's interval, and no run-until driver; P2 was revised and P3's rationale changed.  The survey (R1) classifies every document by which of these it uses.
2. **Incremental stepping with state hand-off (covered for state that is in the model).**  Every ODE and stochastic simulation, `SteadyState` and `FluxBalanceAnalysis` export `[id].model` ("the model's end-of-run state is always also available as `[id].model`"), a later task takes that as its `model`, `independentVariableInit` (its description is still a placeholder) is where the independent variable starts, and `OneStepODESimulation` and `OneStepStochasticSimulation` take one step.  Not covered: state that is not in the model (a process's own memory, a random number generator's state, a cache).  The specification itself leaves open that `OneStepODESimulation` neither tracks nor outputs the independent variable's final value (section 10 of the specification).  The survey counts documents that need hidden state between ticks.
3. **Parameter estimation and fitting (missing).**  There is no estimation task, objective or optimizer.  The nearest things are `ParameterScan` and `Scatter` to enumerate candidates, and a COMBINE 2026 note in the specification that wants an `AggregationCalculation` usable as an objective function ("fit and return the best").  viva-copasi has a `ParameterEstimationStep`.  The survey counts its uses and what data it compares against.
4. **Dynamic and hybrid FBA (covered, with open points).**  The earlier hypothesis that SED2 defers FBA is out of date: `FluxBalanceAnalysis` (KISAO:0000437) is specified, has no independent variable and exports a dictionary of fluxes and `[id].model`.  Dynamic FBA is a `Loop` of an ODE step and an FBA, with `ModelChange` `setValues` passing bounds and fluxes between them (`templates/cosimulation.sed2.json`; sed2-test-suite cases 00274 to 00282; the translators run them).  What the specification does not state is listed in the section "Flux balance analysis and the cosimulation template" of `TODO.md`: infeasible problems, the meaning of an FBA's `[id].model`, outputs that are not reactions, models without the FBC package, and the template's own errors.  The survey classifies FBA documents by whether the model is SBML with FBC (translatable) or exists only in the COBRApy object.
5. **Spatial and particle models (missing).**  No task classes and no model languages: `ModelImport` takes a `language` URN, but only SBML and CellML have appendices (labels, `setValues`, `ModelChange`, element types, Jacobian, steady state).  `AnnotatedData` is an n-dimensional array with labeled coordinates, so a field could be carried as data, and `Plot3D` and `Surface` exist for plots (`surfaceMesh`, `heatMap`, `contour` and others).  Missing: model languages for the engines (Smoldyn, ReaDDy, MEDYAN, LAMMPS, CompuCell3D, tyssue), spatial simulation tasks, trajectory data.  The survey records which engines appear and what they emit.
6. **Rule-based and stochastic simulators (stochastic covered, rule-based missing).**  The earlier hypothesis that stochastic tasks are deferred is out of date: `ExplicitStochasticSimulation`, `BoundedStochasticSimulation` and `OneStepStochasticSimulation` are specified (KISAO:0000319, Monte Carlo) with common fields such as `seed` (`AbstractStochasticSimulation`), and the algorithm is named by KiSAO id in `workingAlgorithms`, not by a class.  Stochastic differential equations are explicitly a different thing.  Missing: a rule-based model language (BioNetGen, Kappa, NFsim input).  The survey separates Gillespie-style documents on SBML (translatable) from rule-based ones.
7. **Dynamic structure (partly covered between tasks, missing within a run).**  `ModelChange` has `addElements`, `removeElements` and `replaceElements` (the specification flags `replaceElements` as a candidate for removal), so a structural change at a `Loop` iteration is expressible.  Not expressible: growth, division, creation or removal during a run, or a `Repeat` whose count changes while it runs (ranges are fixed up front).  `process-bigraph-clock.md` (G6) does not recommend adding it.  The survey counts the documents that need it, to confirm that decision.
8. **Event-driven and conditional execution, gating (missing).**  Every task of a document runs, in file order; there is no conditional task, no trigger and no early exit from a `Loop`.  `Calculation` can select a value (SBML's `piecewise` is among the functions it allows) but cannot skip a task.  Events inside an SBML model are the model's business and not SED2's.  G4 (run until a condition) and G7 (event-driven steps, not recommended) of the clock file apply.  The survey counts templates and sites in use.
9. **Studies as tasks (largely covered).**  `ParameterScan` (one dimension per scanned element), `Scatter` and `Loop` with `aggregateOutputVariables` (an `AggregationCalculation`: sum, mean, standard deviation and so on, KISAO:0000824, for very many repeats without keeping every result), `DrawFromDistribution` (the SBML distrib distributions, with `outputPersistent`) for sampling, and `SteadyState`, `JacobianFull` and `JacobianReduced`; the metabolic control analysis quantities are proposed in `TODO.md`.  Missing: global sensitivity designs (Sobol, Morris), time-course sensitivities (left out of the MCA proposal) and optimization (item 3).  The survey measures how many "study" documents reduce to a scan or a scatter plus an aggregation.
10. **Unit-aware ports and automatic conversion (missing).**  `AnnotatedData` has labeled coordinates and dimensions but no unit field; the only `units` attribute is `CsvImport`'s list of strings (its description is still a placeholder).  Units live in the model (SBML).  The importer would drop `_units` with an entry in its report unless the specification gains a field.  The survey counts the documents that use units.
11. **Output persistence and streaming (outside the specification by design).**  `Report` "only dictates what data must be exported, never the storage format", `Plot` likewise, and an output is always terminal.  An emitter's rows per tick are a `Report` over a time-course table; SQLite, Parquet and JSON are storage choices, so this goes in the "considered and left out" section unless the survey shows incremental emission is needed.
12. **Provenance (mostly missing).**  Every element may carry `name`, `description`, `notes` and `annotations` (qualifier/value pairs such as `dc:title` and `bqbiol:hasPart`), the document has a `version`, and `ModelImport.location` is a URI.  There is no field for pinned code versions or content-addressed results.  Probably "considered and left out", with the importer recording commits in its own report; the survey decides.
13. **Calculations between steps (covered for arithmetic).**  Added after reading the specification: process-bigraph's `MathExpressionStep` (tutorial 3) maps to `Calculation`, an infix expression over references with element-wise broadcasting, the SBML functions and constants.  Not covered: arbitrary Python in a step.  The survey records which steps are plain expressions and which are code.

Statuses are those of 2026-10-09 and change when the specification does.  The corpus decides which of these survive; expect some to drop out and others to appear.

## 10. Risks

* **Sampling bias.**  The corpus is mostly written by one group, and many documents are demos.  Counts show what is in
  the ecosystem, not what scientists need.  `SURVEY.md` will say this.
* **Recognition by name is fragile.**  Renames, shims and subclassing can hide a known class.  Version ranges in the
  recognition table and a test per entry reduce, not remove, this.
* **Hidden semantics.**  Defaults inside wrapper code (tolerances, start time, how many points) are not in the document.  They are
  read from the wrapper's source for each version and written into the recognition table, then checked by the
  verification run, not assumed.
* **Run length** is outside the document (section 2).  Taking it from `default_n_steps` is a guess when only a spec
  provides it; the report records where each value came from.
* **Licences.**  Check before copying a document into any repository.
* **Rate limits and blocked endpoints** (section 4.2).  The survey must be restartable and must record what it could not reach.
* **Original packages are heavy** to install for the verification run; only tier A is attempted.
* **A moving target.**  Repositories change, which is why every item is pinned to a commit.

## 11. Questions for you, and answers so far

Answers given 2026-10-08.  This direction was set aside for the work SED2 to Process Bigraph (`process-bigraph.md`) and taken up again on 2026-10-09; the questions were items T-2 to T-9; all are answered (2026-10-10) except the environment item T-10 (OpenCOR), which is unblocked and in `work/todo/deferred/`.

| Question | Answer so far |
|---|---|
| 1. Where does the corpus live, and may copies be committed? | **Decided 2026-10-10:** local copies only in the git-ignored `corpus-cache/`; every script and test checks for the file and otherwise downloads it from GitHub at a pinned commit (`corpus/manifest.json`), so they run locally and in GitHub CI. Nothing of the documents is committed. |
| 2. How is the repository list built, and what is the scope? | **Decided 2026-10-10:** you saved the API listing (two pages, 156 repositories); the scope is every repository that is neither archived nor a fork (121), shallow-cloned; four over 400 MB are skipped. |
| 3. Name and place of the SED2 proposal file | **Decided 2026-10-10:** leave the files where they are; `process-bigraph-clock.md` and this plan are temporary documents, deleted entirely once the plan is implemented in SED2. |
| 4. Partial translation (`--allow-loss`) | **Decided 2026-10-10:** no partial translation; a document is translated whole or not at all. Carrying the untranslatable parts in `pbg@` namespaced tasks is a possible later test of SED2 namespaces (SED2's TODO.md, low priority). |
| 5. Inline Antimony models | **Decided:** translate them to SBML with libAntimony at import. |
| 6. Run length when the document gives none | **Decided 2026-10-10:** the SED2 document has a top-level constant `duration` and the time range ends at `#constants:duration`. Its value is the number a script that calls the document passes to `run(...)` if one can be found, else 1; `--duration` overrides both. The report says where the number came from. |
| 7. Where do the importer and the mapping table live? | **Decided 2026-10-10:** both translators use libsed2 and neither depends on the other; the two mapping tables stay separate. pbg2sed2 back-translates its SED2 to Process Bigraph as a test in CI (`scripts/pbg_verify.py --via pbg`), not as part of the translation. |
| 8. What does a skipped branch contribute? (clock question 5) | **Decided 2026-10-10:** the held value is the default; gaps selected by an attribute of the output are a possible design option, not proposed yet. |
| 9. What do the project notes say about who wrote what? | **Done 2026-10-10:** the CLAUDE.md files of pbg2sed2, pySED2Translate and sed2-test-suite say you are the author of Antimony and a maintainer of libSBML, roadrunner and Tellurium, and that you and Claude are the authors of everything SED2 related. |

The questions as asked:

1. **Where does the corpus live, and may copies be committed?**  Options: a new directory in this project, a separate
   repository, or only a manifest plus extraction scripts (nothing copied).  The last needs no licence check.
2. **How should the repository list be built?**  The API is blocked in this session.  Can you save the output of
   `gh repo list vivarium-collective --limit 300 --json name,description,isArchived,pushedAt,licenseInfo` on your machine into the
   project?  Also: is the scope only `vivarium-collective`, or also projects that merely use process-bigraph (for example
   `CovertLab/vEcoli`)?
3. **Name and place of the SED2 proposal file.**  (The SED2 folder is connected now, as of 2026-10-09; the place is still open: `SED2/proposals/` or a section of `TODO.md`.)
4. **Partial translation.**  (Answered: all-or-nothing.)  Is "SED2 for the extractable core plus a loss report, only with `--allow-loss`" acceptable, or
   should the importer be all-or-nothing?
5. **Antimony models.**  SED2 imports models by location and language.  Should the importer convert an inline Antimony string to
   an SBML file (the suite already uses antimony for its inputs), or refuse?
6. **Run length.**  When a document does not give one, should the importer refuse, take `default_n_steps` if present, or take a
   `--duration` argument?  The plan assumes: `--duration` if given, else `default_n_steps` with the source recorded, else refuse.

## Sources

* process-bigraph repository (README, docs/, composite_spec.py, composite_discovery.py, the 2026-06-28 CompositeSpec design
  note): https://github.com/vivarium-collective/process-bigraph (git e5325c1, version 1.8.5)
* viva-tellurium: https://github.com/vivarium-collective/viva-tellurium
* viva-copasi: https://github.com/vivarium-collective/viva-copasi
* This project: `process-bigraph-clock.md` and `work/INDEX.md` (this repository); `process-bigraph.md`, build.md, CLAUDE.md, docs/deferred.md, docs/libsed2-api-notes.md (pySED2Translate)
* The SED2 specification and its open points: `SED2/SPECIFICATION.md` (class reference), `SED2/core-spec.md`, `SED2/TODO.md`
