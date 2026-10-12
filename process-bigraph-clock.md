# SED2 and Process Bigraph's clock: what SED2 cannot say, and how to extend it

Location: this file moved here from pySED2Translate on 2026-10-10 (the translator repository is `pbg2sed2`).  Names without a repository, such as `process-bigraph.md`, `build.md`, `CLAUDE.md`, `docs/deferred.md` and `docs/libsed2-api-notes.md`, are files of `pySED2Translate`; `work/` is this repository's git-ignored work directory.

Status: analysis and proposals.  Nothing here is implemented, and nothing here has been put into the SED2 repository
(those files belong to the SED2 author; per CLAUDE.md a proposal goes in a new section at the end of `SED2/TODO.md`,
which is a later step, phase R6 of `process-bigraph-to-sed2.md`).  All SED2 snippets are sketches in the current
`_type` syntax and have **not** been checked with libsed2.
Researched 2026-10-09 against process-bigraph 1.8.5 (git e5325c1).  "Tested" means run in a scratch environment
(experiments listed in `process-bigraph.md`, section 2.9); "read" means found in the source or documentation only.

Evidence review, 2026-10-09 (later the same day): the vivarium-collective application repositories and the process-bigraph test suite were read for how the clock is actually used, and every proposal was re-tested against what was found.  The log is section 8.  Text changed because of it is marked "(revised after the evidence review)" in section 5.

The paper (arXiv:2512.23754v2) and its two supplements were read on 2026-10-09; what they say about orchestration is
folded into section 2 below and into `process-bigraph.md`, section 2.10.

Companion files: `process-bigraph.md` (SED2 -> PBG plan, including the cosimulation test case, section 5.1) and
`process-bigraph-to-sed2.md` (the reverse plan, set aside for now).

## 1. Summary

1. **What works.**  A SED2 `Loop` really is a clock.  Its range is the tick sequence, `.index` and `.range` are the clock
   readings, `loopVariables` are the state handed from tick to tick, and the sub-tasks are what runs at a tick.  The
   attached cosimulation document therefore translates to a process-bigraph clock loop (`process-bigraph.md`, 3.8 and
   5.1) with the sub-tasks as steps.  That is the case where **sequential operator splitting** is wanted, and SED2
   already says it.
2. **Parallelism is also already there.**  (Corrected after your question about Scatter.)  Tasks that do not reference
   each other are independent by construction, so a SED2 task graph is already a parallel-friendly DAG; `Scatter` says
   "these iterations are independent, run them in parallel if you like" for many copies of one body; and any task may sit
   inside a Loop or a Scatter.  So *simultaneous coupling* of the process-bigraph kind is expressible today: in each
   Loop iteration the branches read only the loop variables (not each other), either as sibling sub-tasks or as a
   Scatter, and a Calculation merges their results into the next loop variable.  Tested: a Scatter nested in a Loop that
   reads the loop variable validates with libsed2 (0 problems).  Many identical processes (Spatio-Flux's per-cell
   `DynamicFBA`) are exactly Scatter-in-Loop.
3. **What SED2 cannot say about the clock** is therefore narrower than first written: (G1) several processes with
   *different* intervals on one timeline, (G3) a process that chooses its own next step (adaptive interval), (G4)
   running until a condition rather than for a fixed count, and (G5) a process that keeps internal state between ticks.
   (G2) *simultaneous coupling* is expressible but not *nameable*: nothing says "these branches read one snapshot and
   their changes add", the merge is an explicit Calculation, and for a model-valued loop variable that merge is
   heavy.  Two more (G6 dynamic structure, G7 event-driven steps) are not worth importing.
4. **The distinction that still matters** is semantic: the same two models give different numbers when chained
   sequentially and when run as parallel branches on one snapshot (tested: after one tick the second state is 0.125
   sequentially and 0.25 in parallel, section 2).  Both are writable in SED2; a reader (or a reverse translator) can
   only tell them apart by inspecting which references the sub-tasks make.  A label would help (P1, now optional).
5. **Proposals** (section 5), ordered by value for the cost: P2 a `Clock` as a range with a *time* meaning and
   per-sub-task periods (G1); P3 `Loop.until` with a mandatory `maxIterations` (G4); P1 an optional `evaluation` label
   and `combine` rule for parallel branches (G2, convenience and recognisability, not expressiveness); P4 a `nextRange`
   expression for adaptive steps (G3); P5 continuation state as a first-class task output (G5).  P6 and P7 are listed
   as "do not add".  Each proposal keeps the SED2 invariant that the shape of the result is known before running (rows
   padded to `maxIterations`, plus a count).
6. **Evidence review (section 8).**  The repositories show one dominant pattern (one interval per document; the only mixed intervals in authored documents are the integer multiples 1.0 and 50.0 of two flagella documents), a few recurring clock idioms that the first draft did not list (time-window interventions, a step that needs the elapsed interval, a step that sets a process's next interval, drivers that run for a fixed number of ticks) and no driver that runs until a condition.  Result: P2 is kept but needed four changes (an active window, a defined meaning for a skipped sub-task, exposing the step length, exact decimal arithmetic for periods); P3 stays, but its evidence comes from stochastic event stepping and not from process-bigraph drivers; P4 and P5 stay deferred; P1 gains a reason, because it defines what a branch that did not run contributes.  Dynamic structure (G6) recurs in the two largest application repositories and is still not recommended, but a bounded form is expressible with masks.

## 2. What Process Bigraph's clock is

The facts that matter, with their status.

| Fact | Status |
|---|---|
| A **process** is a node with an `interval`.  Global time is the `global_time` store; it advances to the earliest due process; a process due at t reads the state, runs `update(state, interval)` and its update is applied at the *end* of its interval. | Tested |
| Each process reads a **snapshot taken at the start of its interval**.  Two processes with equal intervals both read the state as it was before either update (Jacobi coupling).  A process with a longer interval reads a stale snapshot. | Tested |
| An update is **merged by the type of the output port**: `float` adds a delta, `overwrite[T]` replaces, `map[...]` merges per key.  So coupling by addition ("both processes change this store") is a property of the *type*, not of the process. | Tested (`float` delta, `overwrite`); other merges read |
| `Process.calculate_timestep(interval, state)` lets a process **shorten or choose** its own interval from the current state. | Read (hook in `composite.py`; not exercised) |
| **Steps** (no interval) run when an input path is updated, in dependency order, at every tick that updates it.  A step downstream of a process re-fires every tick. | Tested |
| All steps with no ready input fire once at the start of `run()`, even with `run_steps_on_init: false`. | Tested |
| `Composite.run(T)` runs until `global_time` reaches T; there is no "run until" a condition in the framework (a step or process could stop producing updates; nothing ends the run). | Read |
| A process is an **object with state between ticks** (the Python instance lives as long as the composite). | Tested (the clock keeps its counter) |
| **Dynamic structure**: updates may contain `_add`, `_remove` and `_divide` sentinels that create or delete nodes and stores while the run is in progress (cells appear and divide). | Read (`composite.py`, `processes/dynamic_structure.py`, `growth_division.py`) |
| **Specification versus implementation.**  The formal small-step rule (S1 3.8.2) updates all processes due at the same event time "conceptually in parallel when their deltas commute", reading inputs at the event time; deltas to one store are combined and *reconciled* by a type-specific rule before they are applied (S1 3.8.3).  So parallel reads for equal intervals are specified behaviour.  For unequal intervals the rule reads at the event time while the implementation reads at the start of the process's interval (row above); the text does not settle which is meant.  Settled afterwards by the maintainers' own test (E14): read at the start, apply at the end. | Read (S1) against tested (implementation) |
| A Composite is itself a Process, so clocks nest, and a Step may host a whole inner composite (`SimulationStep`, `RunProcess`). | Read; the hosting pattern tested |
| `ProcessEnsemble`, `BigraphicalReactiveSystem`, `ReactionStep`: reaction-like and rewrite-rule processes. | Read |

Numbers behind the second row (tested, `x' = x + 0.5 (y - x)`, `y' = y + 0.25 (x - y)`, start x = 1, y = 0):

| Scheme | After tick 1 (x, y) | After tick 2 (x, y) |
|---|---|---|
| Two processes, equal intervals (process-bigraph, measured) | 0.5, 0.25 | 0.375, 0.3125 |
| Same updates computed in parallel by hand | 0.5, 0.25 | 0.375, 0.3125 |
| Same updates in sequence, second reads the new x (what a SED2 loop with two chained sub-tasks does) | 0.5, 0.125 | 0.3125, 0.171875 |
| Intervals 1 and 2 (p2 slower) | t=1: 0.5, 0.0 | t=2: 0.25, 0.25 (p2 used the t=0 snapshot) |

## 3. What a SED2 Loop can already say about a clock

| Process-bigraph | SED2 | Fit |
|---|---|---|
| A tick, k = 0, 1, 2, ... | `Loop` iteration; `#tasks:loop.index` | exact |
| Time at tick k = k * interval | `#tasks:loop.range` (a `numericRange`) times a constant, via a Calculation | works, but nothing says the range *is* time |
| State handed to the next tick | `loopVariables` (`initialValue`, `subsequentValues`) | exact |
| What runs at a tick | `subTasks`: any task, in reference order; siblings that do not reference each other are independent; a `Scatter` for many copies of one body | exact, sequential or parallel as the references say |
| Several processes reading one snapshot and merging their changes | branches that read only loop variables (siblings or a nested Scatter) plus a Calculation that merges | expressible; the intent is not labelled and a model-valued merge is verbose (G2) |
| Observation of every tick (emitter) | `outputVariableMap` + `Report` | exact |
| A model advanced by an integrator for one interval | `explicitODESimulation` etc. restarting from the previous `.model` | exact; the integrator restarts (see G5) |
| Two models alternating (the cosimulation) | `ModelChange` with `setValues` from the other simulation's result | works; id mapping is the author's job |

So the single-clock, sequential case is covered.  Everything below is about leaving that case.

## 4. Where SED2 cannot express the clock

Each gap lists the process-bigraph behaviour, why SED2 cannot say it, what the translator does today, and which
proposal in section 5 addresses it.

### G1 - Several processes with different intervals

*PBG.*  A fast process (interval 0.1) and a slow one (interval 1.0) share a timeline; the slow one sees the fast one's
state as of the start of its interval (implementation; the formal rule in S1 3.8.2 may mean the state at its event
time, section 2).  The framework schedules by the earliest due time.  Because of that open point, P2's "stale read" rule
below is written against the implementation and was confirmed by the process-bigraph authors' own test (E14) and can go into
a specification.

*SED2.*  A loop has one range.  A sub-task runs at every iteration.  One can emulate multi-rate by hand (an outer loop of
the slow clock with an inner loop of ten fast iterations), but only when the intervals are integer multiples, the
nesting is written out, and the stale-read behaviour (the slow task reads state from the start of its interval) is not
what the nested form gives (the fast loop finishes before the slow task reads).  Intervals with no integer ratio (0.3 and
0.5) cannot be written by nesting at all (with P2 they can: a range whose step is the common tick 0.1, and `every` 3 and 5).

*Translator today.*  Sequential loops only.  A PBG document with unequal intervals (reverse direction) is **not
translatable** except when the intervals are integer multiples (nested loops) or, after P2, share a common tick, and then only if the author accepts a different numerical scheme.

*Proposal.*  P2.

*Evidence (section 8, E1, E2, E13).*  Two authored documents mix intervals (1.0 with 50.0, the two flagella documents of the legacy corpus: integer multiples); one unit-test document mixes 0.1 and 0.25 (no integer ratio, common tick 0.05); the maintainers' own multi-rate test uses 1 and 2 (E14).  spatio-flux's "multi-timestepping" figure is a drawing composite that is not simulated (E2).  Every other document or composite uses one interval.  Any two decimal intervals have a common tick, so "non-commensurate" in the sense of no common tick cannot occur with decimal intervals.  Process-bigraph itself decides on decimal digits (E13), so "commensurate" has to be decided in exact decimal arithmetic.

### G2 - Simultaneous (parallel) coupling and additive updates

*PBG.*  Equal-interval processes read the same snapshot and their updates merge by type (deltas add).  This is
the standard way to couple models that act on shared state "at the same time", and it is order independent.  The
specification adds *reconcilers*: when several deltas hit one store they are combined by a type-specific rule (summed for
numbers, put in a canonical order for structural edits), so the merge is a property of the store's type.

*SED2.*  Expressible today, in three ways, all of which keep the parallelism visible in the reference graph:

1. **Sibling sub-tasks of a Loop that read only the loop variables** (never each other): by construction they are
   independent and see the same snapshot; the next loop variable is a Calculation that merges them, for numbers and
   arrays `x + (r1 - x) + (r2 - x)`.
2. **A `Scatter` inside the Loop** for many copies of one body (one per cell, particle or site): each iteration reads its
   own slice of the loop variable, the Scatter stacks the results, a Calculation or the stack itself becomes the next loop
   variable.  This is the Spatio-Flux per-cell pattern.  Tested: Scatter in Loop, Loop in Loop and Scatter in Scatter all validate (0 problems; validation only, nothing was run).
3. **A `Scatter` of Loops or a Loop of Scatters** as the problem requires; any task can be inside a Loop or a Scatter.

What SED2 does not have: (a) a statement of *intent* ("these branches are one coupling step; their changes add"), so a
reader cannot tell a parallel scheme from a sequential one without tracing references; (b) a merge for **model-valued**
loop variables: `ModelChange` replaces values, so merging two branches' changes to one model means extracting species or
parameter values (ModelElementList, Calculation, RelabelData), summing the changes, and writing the result back with a
ModelChange: possible, long, and easy to get wrong; (c) any notion of reconciling non-numeric updates.  The numbers differ
from the sequential scheme (section 2 table), so the choice between the two is a real modelling choice that the
document makes only implicitly.

*Translator today.*  Forward: the reference graph decides; sibling sub-tasks that do not reference each other are
independent and may run in dependency layers, a Scatter inside the Loop is a nested `SedRepeat` step inside the inner
composite (`process-bigraph.md`, 3.8).  Reverse: a PBG document with equal-interval processes sharing a store maps to a
Loop whose branches read the loop variables, plus an explicit merge Calculation; this is *translatable today* for
numeric and array stores, and the reverse translator must emit the explicit snapshot reads, never a plain sequential
chain (which would silently be a different scheme).  Model-valued merges are the hard case.

*Proposal.*  P1, now optional: a label and a merge rule, so that the pattern above is declared and not reverse
engineered.  Not an expressiveness gap.

*Evidence (section 8, E11).*  The parallel-snapshot reading is relied on in practice: the Ray shard manager of spatio-flux evaluates all shards from one read of the fields and adds the results back by direct array writes, which is only correct because additive deltas to disjoint cells commute.  A translator must therefore take the semantics from the document (shared store and type), never from a runtime hook.

### G3 - A process that chooses its next interval

*PBG.*  `calculate_timestep` can return a shorter step depending on state (adaptive coupling, event handling, error
control).  The clock then has non-uniform ticks decided during the run.

*SED2.*  The range of a Loop is fixed before the loop starts and "cannot end early".  SED2 ranges can be non-uniform
(an explicit `values` list, `log10` scale), but they cannot depend on results.

*Translator today.*  Not translatable; a PBG process whose `calculate_timestep` is overridden is refused.

*Proposal.*  P4 (and P3 is a prerequisite for open-ended runs).

*Evidence (section 8, E6, E7).*  No application repository overrides `calculate_timestep`.  The one working example of a self-chosen interval is a different mechanism: in process-bigraph's Gillespie composite a Step draws the waiting time and writes it to the `interval` of the event process (`['event', 'interval']`), and the engine re-reads `process['interval']` from the state every time it schedules.  So a reverse translator has to look for two forms: an overridden `calculate_timestep`, and a Step whose output is wired to a process's `interval`.  The Gillespie case is also exactly what SED2's `OneStepStochasticSimulation` with no `independentStep` already does (it reports the step taken as `[id].independentStep`), so P3 with a time loop variable covers it and P4 is not needed for it.

### G4 - Run until a condition

*PBG.*  The host decides how long to run; documents often run "until the population reaches N" or "until a steady
state" by wrapping `run()` in a Python driver, not in the document.  Within the document nothing ends the run
either, so this is mostly a gap of the *drivers around* process-bigraph, and of what the reverse translator sees as
intent.

*SED2.*  `Loop` has a required range and cannot end early; `SteadyState` is a separate simulation.  A converged
fixed-point iteration or "stop when the FBA growth rate falls below x" is impossible, or needs a worst-case range with
dead iterations that still run their sub-tasks.

*Proposal.*  P3, with a mandatory `maxIterations` so that the result keeps a known shape.

*Evidence (section 8, E8).*  About 40 `run(...)` calls in the application repositories and their tests were read; every one runs for a duration given up front (a literal, a constant, a parameter, or a count times an interval).  None runs until a condition, and a search for loops around `run` with a convergence or time test found none.  The documented need for P3 therefore comes from SED2-side uses (stochastic event stepping, converged iterations), not from process-bigraph usage.

### G5 - A process with internal state between ticks

*PBG.*  A process instance is long-lived: an integrator keeps its step-size history, a stochastic simulator keeps its
random generator, a wrapped simulator keeps its Jacobian or factorisation.  Continuing is cheap and exact.

*SED2.*  State between iterations is whatever the `.model` carries (end values of the model).  A new simulation restarts
the integrator: the result of 100 intervals of length 20 is not identical to one interval of length 2000, at the
solver's tolerance.  For a stochastic simulation the generator state is not part of the model, so a loop of short
stochastic runs cannot be made equivalent to one long run, and cannot even be reproduced from a seed unless every
iteration is given a derived seed.

*Translator today.*  Restart semantics.  Differences are within tolerance for ODEs and are a real difference for
stochastic runs (stochastic is out of scope for now).

*Proposal.*  P5.

*Evidence (section 8, E9).*  Every instance of between-tick state found is plain explicit state that SED2 can hold in a loop variable: the tick counter of `Clock`, `_elapsed` and `_frozen` of `Intervention`, the internal state of the consumer-resource process in crm-fba, the wrapped OpenCOR wrapper's own time.  The roadrunner wrapper in viva-tellurium pushes the incoming species values into one long-lived instance and simulates from its current time, which is the restart semantics SED2 already has.  Nothing found needs opaque solver state.  The difficulty for the reverse translator is different: Python instance attributes are not in the document, so a process class that is not known to the translator cannot be mapped at all.

### G6 - Dynamic structure (not recommended)

*PBG.*  `_add`, `_remove`, `_divide` change the set of nodes during a run (a cell divides, an agent dies).  The size
of the output is not known in advance.

*SED2.*  The whole language assumes a static task graph and result shapes known before running.  Dynamic structure would
remove that, and with it the ability to check a document without running it.

*Recommendation.*  Do not extend SED2.  A PBG document that uses these constructs is simply out of scope for the reverse
direction, and the report should say so in one line.  A restricted case ("a fixed set of agents, some of them
inactive") is already a Scatter over a list with a mask.

*Evidence (section 8, E10).*  Dynamic structure is not rare in the application repositories: cdFBA's `DFBALauncher` adds and removes dFBA species when a concentration crosses a threshold, and spatio-flux divides particles at a mass threshold in its reference, particles and comets composites.  It is absent from the 68 documents of the process-bigraph corpus.  The recommendation stands (refuse, with a one-line reason), with one refinement: when the candidate names are in the configuration (cdFBA) or the count has a cap, the case is a masked Scatter over a fixed set and can be translated; unbounded growth cannot.

### G7 - Event-driven steps (not recommended as a separate construct)

*PBG.*  Steps fire when inputs change: derivers, reaction steps, mass listeners.  In a SED2 loop a derived quantity is a
sub-task that runs at every iteration, which is the same thing, so nothing is missing inside a loop.  What SED2 lacks is
firing *between* ticks (on an event in the middle of an interval), which belongs to the simulation (SBML events), not
to the task layer.

*Recommendation.*  Nothing to add.  Note the difference in the reverse report: a PBG deriver downstream of a process
becomes a sub-task of the loop, and its firing count equals the tick count.

### G8 - Smaller points

* **Time is not a first-class value.**  `global_time` is a store anyone can read; in SED2 the nearest is the range of
  the loop, with no statement that it is time.  P2 fixes this.
* **Time precision.**  `global_time_precision` rounds times.  SED2 has no equivalent, and needs none until P2.
* **Where steps run at start.**  All steps fire once before the first tick with default inputs (tested).  Nothing in
  SED2 corresponds, and the translator hides it (the index guard in `process-bigraph.md`, 3.8).  A PBG document
  written for the framework's behaviour may *depend* on that first firing (initial values derived from other stores).
  The reverse translator needs a rule: a step with no process upstream is a task before the loop.
* **Initial emission.**  `run(0.0)` is used by the application repositories (viva-biomodels) only to run the steps and flush the emitter once, i.e. to record the state at the initial time.  In SED2 this is a Report row for the initial state, which a Loop over a range that starts at the first tick does not produce unless the author adds it (E8).

## 5. Proposed SED2 extensions

These are proposals for the SED2 author.  They are small on purpose, keep the "result shape is known in advance" rule,
and are ordered by value.  The sketches use the current syntax and are not validated.

### P1 - an `evaluation` label and `combine` rules for parallel branches (optional)

Parallel branches can already be written (G2).  This proposal only makes them *declared and checkable*.

Add to `Loop` an optional `evaluation`:

* `"sequential"` (default; today's meaning): each sub-task may read its siblings' results of the same iteration.
* `"parallel"`: sub-tasks read only the loop variables and outer tasks, never a sibling of the same iteration (a
  validation rule: a reference to a sibling's result is an error).  This is a *checkable assertion about a document that
  could be written today*, like Scatter's "iterations are independent", and lets a reader and a reverse translator
  recognise the coupling scheme without tracing references.

Add to each loop variable an optional `combine`, used only with `parallel`: how the results of several sub-tasks that
write the same variable are merged into `subsequentValues`.  This removes the long Calculation (and, for models, the
extract-sum-ModelChange chain).

```json
"repeat": {
  "_type": "loop",
  "evaluation": "parallel",
  "range": { "_type": "numericRange", "start": 0, "end": 2, "numberOfSteps": 2 },
  "loopVariables": {
    "x": { "initialValue": "#constants:x0", "combine": "sum-of-changes",
           "subsequentValues": ["#tasks:repeat:subTasks:p1.data", "#tasks:repeat:subTasks:p2.data"] }
  },
  "subTasks": { "p1": { "...": "reads #tasks:repeat:loopVariables:x" },
                "p2": { "...": "reads #tasks:repeat:loopVariables:x" } }
}
```

`combine` values to start with: `"replace"` (exactly one writer allowed), `"sum-of-changes"` (new = old + sum of
(result - old); for a model-valued variable, applied to the values of the model elements that changed), nothing else.
This is process-bigraph's `overwrite[T]` versus `float`-delta split, made explicit.

Cost: a new validation rule (no sibling reference in a parallel loop), one new field per loop variable.  Risk: low.
Value: moderate, because the pattern works without it; the largest benefit is model-valued merges and recognisability.
A smaller alternative with most of the benefit: a documented *pattern* in the SED2 specification (a worked example of
Scatter-in-Loop with a merge Calculation) and no new fields.

*Revised after the evidence review.*  The review (E3, E11) gives P1 a second job: it defines what a branch that did not run in an iteration contributes.  In `sum-of-changes` a branch that did not run contributes no change, which is exactly the process-bigraph rule that a slow process updates only at the end of its own interval.  P2 below uses the same rule, so the two proposals should be accepted or deferred together, or P2 should state the rule on its own (it does).

### P2 - Time-valued ranges and per-sub-task periods (a `Clock`)

*Revised after the evidence review (E1 to E5, E13).*  Four pieces:

1. A range may be declared as **time** (`"meaning": "time"`, with optional unit), exposing `#tasks:loop.time` (the value) and `#tasks:loop.step` (the time since the previous iteration).  This is mostly a label, and gives the reverse translator something to map `global_time` onto.  `.step` is new: process-bigraph hands every process the length of its interval, and crm-fba's FBA step needs it as data (`growth * biomass * interval`), so a Calculation in a loop must be able to read it without carrying the previous range value by hand in a loop variable (E5).
2. A sub-task may carry `every` (an integer number of ticks) or `period` (a time that must be an integer multiple of the range step).  It runs only at iterations whose tick is a multiple, and reads the loop variables as they stood **at its last run** (stale read, as in process-bigraph).  Its `#tasks:loop:subTasks:name.elapsed` is the time since its own last run, which is the `interval` argument a process-bigraph process receives.
3. A sub-task may carry `window`, a pair `[start, stop)` in the units of the range: it runs only while the range value is inside the window.  This is the shape of the `Intervention` process (E3), which is the one place where the application repositories gate an action on time: apply a clamp, a knock-out or a bolus between two times.  `every` and `window` combine (run every k ticks inside the window).  A single-time event is a window one step wide.  Evidence is thin: the class exists but no surveyed document uses it (E3), so `window` is the first piece to drop if P2 should be smaller.
4. **What a sub-task that did not run contributes** (this replaces the first draft's "carried over", which is wrong for state; see below).  A skipped sub-task changes nothing: a model-valued output equals the sub-task's input model, a numeric or array output that feeds a loop variable contributes zero change (identity under `replace`, zero under `sum-of-changes`), and a data output that is only reported holds its last value, or the documented fill value before the first run.

```json
"subTasks": {
  "fast":  { "...": "...", "every": 1 },
  "slow":  { "...": "...", "every": 10 },
  "pulse": { "...": "a ModelChange", "window": [5, 8] }
}
```

Why the first draft's rule fails: it said a skipped sub-task's result is "carried over", meaning its previous output.  Test on paper with the window-gated ModelChange of E3: outside the window its previous output is the model it returned at its last active tick (or the initial model), and if that is what the next loop variable takes, every change the simulation made since then is erased.  A slow process in process-bigraph does not behave like that: between its updates it contributes nothing.  Hence "contributes no change".  (Paper test, not run; the equivalent process-bigraph behaviour was measured in the intervals 1 and 2 row of section 2.)

This covers multi-rate (G1) and windowed events without a scheduler.  Any two decimal intervals have a common tick (their gcd: 0.05 for 0.1 and 0.25, 0.1 for 0.3 and 0.5), so the author, or the reverse translator, chooses a range whose step is that tick and gives each sub-task its `every`; the cost is the number of iterations, run length over tick.  Exactness: `every`, `period` and `window` are evaluated in exact decimal arithmetic on the values as written, because process-bigraph derives time precision from the decimal digits of the step (E13); floating-point multiples such as 3 * 0.1 must not decide whether a task is due.  Cost: moderate (a sub-task may now not run at an iteration; the rule above keeps result shapes fixed).

### P3 - `until`, with `maxIterations`

An optional `until` on a Loop: a boolean expression over the iteration's results (`#tasks:...`), evaluated after each
iteration.  `maxIterations` becomes **required** whenever `until` is present.  Result blocks are padded to
`maxIterations` (a documented fill value) and the loop also outputs `.completedIterations`.  This keeps rows known in
advance (the invariant) and makes "stop when converged" expressible.  Cost: a boolean expression language (SED2
already has MathML-like Calculation, so a comparison of one scalar to a constant would be enough to start), padded
results.  Risk: medium; it is a change to "cannot end early" in the Loop specsheet, so it is the SED2 author's call.

*Revised after the evidence review.*  Kept, with a changed rationale.  No process-bigraph driver runs until a condition (E8), so the case for P3 does not come from process-bigraph.  It comes from SED2 itself: stochastic event stepping with `OneStepStochasticSimulation` and no `independentStep` (E6: a loop with a time loop variable that accumulates `[id].independentStep` and `until` that variable reaches the end time), and converged iterations.  The `until` expression must be able to read a loop variable and a sub-task result; nothing more is needed for the Gillespie case.  Overshoot at the end is the author's choice (the last event may pass the end time, as process-bigraph's default `force_complete=False` also allows).

### P4 - `nextRange`: adaptive steps

Only meaningful together with P3.  Instead of a fixed range, the Loop gives `initialRange` and `nextRange`, an
expression of loop variables and results producing the next range value (the next interval), with `maxIterations`.
This is the SED2 form of `calculate_timestep`.  Cost: high for the benefit, since adaptive coupling is rare in the SED2
domain (the simulators adapt internally).  **Recommend deferring** until a real use case shows up.

*Revised after the evidence review.*  Deferral confirmed, and the one apparent use case does not need it: the Gillespie composite (E6) is served by P3 plus the existing stochastic task.  No application repository overrides `calculate_timestep` (E7).  What remains is detection: a reverse translator that meets a Step wired to a process's `interval` must classify it as G3 and refuse it, not translate it as a plain step.

### P5 - Continuation state as a task output

Today `.model` carries the model's values.  Add an optional output `.state` to simulation tasks and a matching
`continueFrom` input: opaque simulator state (integrator history, random-generator state) that the next simulation
may pick up, with the rule that an implementation which cannot honour it must fall back to a restart *and say so*
(a documented capability, like the other `capabilities.json` entries).  For stochastic simulations it is the only
way to make a loop of short runs equal one long run.  Cost: depends on each backend (roadrunner and COPASI have
partial support; libopencor unknown).  Value: high for stochastic, small for ODEs.  Defer with the stochastic phase.

*Revised after the evidence review.*  Deferral confirmed.  The between-tick state found in the repositories is explicit state (E9) and needs no opaque `.state` output; it needs the translator to know the class.  P5 is only for stochastic generators and integrator history, for which no process-bigraph evidence was found.

### P6 and P7 - not proposed

Dynamic structure (G6) and between-tick events (G7), for the reasons given there.

### Order of work and what each unlocks

| Proposal | Gap | Needs another proposal? | Unlocks in the forward direction | Unlocks in the reverse direction |
|---|---|---|---|---|
| P1 (optional) | G2 | no | declared parallel loops translate to equal-interval processes | equal-interval PBG documents are recognised, and model-valued merges become short |
| P2 | G1, windows (E3), step length (E5) | no (its skip rule is P1's "no change") | multi-rate loops translate to processes with intervals | multi-rate PBG documents map (range step = common tick) |
| P3 | G4 | no | `until` loops translate to a step with a stop flag | drivers of the form "run until x" map (none found, E8); stochastic stepping maps (E6) |
| P4 | G3 | P3 | adaptive loops | `calculate_timestep` processes map |
| P5 | G5 | no | stochastic continuation | stateful processes map |

With P1 and P2 in SED2, a SED2 Loop could be translated to process-bigraph's **native** form (processes with
intervals) as well as to the step form, so the two sections in `process-bigraph.md` (3.8 steps, 3.9 native) would merge
into one: the same document, written the way the framework is meant to be used when you want to *couple* it to other
processes.

## 6. What this means for the translators

**Forward (SED2 -> PBG).**  Nothing in this file blocks the plan.  The clock form (steps inside a hosted inner
composite) is exact for today's SED2, whether the sub-tasks are chained or parallel, because the order inside a tick
comes from the references; a Scatter inside a Loop becomes a nested `SedRepeat` step.  After P2 (and P1, if adopted) the
translator gains a second, native form in which parallel branches become equal-interval processes.  Multi-rate loops
cannot be written in SED2 until P2, so there is nothing to translate before then.

**Reverse (PBG -> SED2).**  Hypothesis 1 of `process-bigraph-to-sed2.md` ("coupled simulation is the largest gap")
should be narrowed to what is now known:

* One clock, one interval, processes with disjoint outputs and no process reading another's output: equals a sequential
  loop (order irrelevant), translatable today.
* One clock, one interval, processes that read each other's outputs or write the same store: *not* equal to a
  sequential loop (section 2 table); translatable today as a Loop whose branches (siblings or a Scatter) read only the
  loop variables, with an explicit merge Calculation (G2); the model-valued merge is the hard part, and P1 would shorten
  it.
* Different intervals: before P2 only when they are integer multiples (nested loops, with the stale-read difference of G1); with P2 whenever they share a decimal tick, which is always (the cost is the iteration count).
* `calculate_timestep` overridden, a Step wired to a process's `interval` (E6), or `_add`/`_remove`/`_divide` with unbounded growth: refused with a one-line reason.  `_add`/`_remove` with candidate names known in the configuration, or a capped count, can be written as a masked Scatter (E10).
* Time-gated processes (`Intervention` with a `window`): a sub-task with a `window` once P2 exists; before that, a split time course.
* A process whose class keeps hidden state (`Clock`, `Tick`, `Intervention`, the consumer-resource process): translated only through a hand-written mapping per known class; an unknown class is refused (E9).
* A Step that reads the elapsed interval (crm-fba's `interval` store): the interval is a constant of the loop, or `.step` once P2 exists.
* Steps between processes: sub-tasks of the loop, firing once per tick; steps with no process upstream: tasks before
  the loop.

A classifier for these cases is the natural first output of the reverse translator, before any SED2 is written: it
would also give a count, over the corpus, of how many PBG documents fall in each class.  That count is the evidence the
SED2 author needs to decide on P1 to P5.  The classifier should record the clock-usage items listed in section 8 (the "What to record per document" table), so that the log below is extended from counts and not from reading.

## 7. Open questions

1. **Is the sequential scheme what you mean by a SED2 Loop?**  The cosimulation document says so (the sub-tasks read
   each other's results).  This file assumes yes for chained sub-tasks, and notes that parallel evaluation of independent branches (siblings and
   Scatter) is already available in SED2, so P1 is a label and a merge rule, not a capability.
2. **P3 versus "cannot end early".**  The Loop specsheet says a loop cannot end early.  Is that a design principle
   (results of known shape; documents that can be checked statically) or a first-version limit?  The padding rule in P3
   is meant to keep the principle, but it is your call.
3. **Should a range know that it is time?**  P2 part 1 is a label only.  It is cheap, but it adds a concept to the
   specification.
4. **Where should proposals go?**  CLAUDE.md says a new section at the end of `SED2/TODO.md`.  I have not written
   one.  Say when, and whether to include all five proposals or only P2 and P3 (P1 is optional, see G2).
   Working position since the evidence review (item T-5): the proposals stay in this file; evidence gathering is a standing track of the reverse plan (record per document in R1, review of the proposals at the end of R1 and again at R6); nothing goes to `SED2/TODO.md` before the R1 counts exist and you have read P1 and P5.
5. **What does a branch that did not run contribute?**  **Decided 2026-10-10 (item T-9):** the held value is the default: no change for state (identity), and for reported data the last value is held (what the surveyed process-bigraph documents do: the store keeps its last value).  A gap in the report (nothing reported for the ticks the branch did not run) is kept as a possible design option, chosen by an attribute on the output, and is not proposed yet; P1 and P2 should say so when they are written up.  The alternative to the default, hold the last output for everything, is wrong for state (section 5, P2).

## 8. Evidence log

The pilot survey of the pbg2sed2 repository (phase R1, 11 clones, static reading; its generated report and counts are in that repository's `work/`) re-checked the counts below mechanically and found the correction in E2.  Its clock-usage table over the 127 authored documents: single interval 102, integer multiples 2, no process 18, interval not a literal 5; documents with processes sharing a store 22; steps with no process upstream 44; a Step wired to a process's interval 0 (3 in test documents, all the Gillespie composite); structural sentinels 0; time windows 0; hidden-state utility classes 0.  Run drivers outside tests: 29 `run(...)` calls (9 literal, 10 named, 6 call results, 2 expressions, 2 other), none inside a while loop, 5 `run(0)`, 1 with `force_complete`.

Read on 2026-10-09 from clones of the vivarium-collective repositories (cdFBA, crm-fba, process-bigraph, spatio-flux, viva-basic-processes, viva-biomodels, viva-comets, viva-copasi, viva-opencor, viva-tellurium, vivarium-cobra).  Status: read, not run, unless stated.  "Tests" names the proposal or gap the finding was held against.

| Id | Finding | Where | Tests | Result |
|---|---|---|---|---|
| E1 | The legacy corpus has 68 documents (66 distinct) with 77 `interval` keys; one interval per document except two flagella documents (1.0 and 50.0); 10 documents have no process; no `calculate_timestep`, `_add`, `_remove`, `_divide` or time window anywhere in it. | process-bigraph `scripts/corpus/legacy_documents.json` | G1, G3, G6, P2 | Holds: multi-rate is rare and commensurate. |
| E2 | spatio-flux `fig06-orchestration` is a drawing composite (draft nodes of class `BigraphLink`, described in the file as not simulated); **the first version of this log wrongly counted it as a document that mixes 0.5 and 1.0**.  No spatio-flux composite mixes intervals, and neither do the Python-built composites of the other repositories. | spatio-flux composites, scripts; found by the pbg2sed2 pilot survey | G1, P2 | Corrected: there is no real multi-rate application document in the surveyed repositories; the multi-rate evidence is E1, E14 and the unit-test document. |
| E3 | (No surveyed document uses it: 0 of 127 authored documents contain `Intervention`, `Clock` or `Tick`; the evidence is the class itself in the maintainers' basic-processes package.)  `Intervention` applies set, knockout, scale, add (optionally times the interval), decouple or invert to one store, once per tick, optionally only while `t0 <= t < t1`, measured on its own elapsed time or on `global_time`.  It keeps `_elapsed` and `_frozen` between ticks. | viva-basic-processes `intervention.py` and tests | P2, G5, G7 | P2 as drafted cannot say a window.  **Changed:** `window` added; the skip rule redefined (see P2, why the first draft fails). |
| E4 | `Clock` counts updates (`tick`) and `Tick` accumulates time into a store, because `global_time` is reserved and the engine keeps no step-count store. | viva-basic-processes `clock.py`, `tick.py` | P2 part 1 | Holds: a time-valued range with `.time` and `.index` covers both. |
| E5 | (A second instance: spatio-flux's `ManageBoundaries` step has a `process_interval` input wired to an interval store, in the fig07-3 and fig08 composites.)  The consumer-resource process writes its `interval` into a store each tick and the FBA step reads it (`growth * biomass * interval`, uptake times interval); the demo and tests also set a second copy of the interval by hand. | crm-fba `processes/crm.py`, `fba.py`, `crm_dfba.py`, `demo.py` | P2, G8 | **Changed:** `.step` and `.elapsed` exposed.  Also a hazard worth a translator warning: the hand-copied interval can disagree with the process interval. |
| E6 | A Step draws an exponential waiting time and writes it to the `interval` of the event process (`['event','interval']`); the engine re-reads `process['interval']` on every scheduling.  The `ProcessEnsemble` variant (`inputs_interval`, `calculate_interval`) is unfinished.  The waiting time is drawn with scale equal to the summed propensity, which looks inverted (the mean wait is its reciprocal); the file calls itself a toy. | process-bigraph `experiments/minimal_gillespie.py`, `tests.py`, `tests/test_events.py` | G3, P3, P4 | G3 has a second form (Step to interval).  P4 not needed: P3 plus `OneStepStochasticSimulation` covers it. |
| E7 | No application repository overrides `calculate_timestep`. | all eleven clones | G3, P4 | P4 stays deferred. |
| E8 | About 40 simulation `run(...)` calls; all durations given up front (literals, constants, parameters, `run(args.run * args.interval)`, `run(steps * dt)`); none until a condition; `run(0.0)` used to flush the emitter at the initial time; `force_complete` is never passed by application code (default False). | cdFBA tests, crm-fba demo, spatio-flux scripts, viva-biomodels, viva-* tests | G4, P3, G8 | No process-bigraph evidence for P3; its case is SED2-side.  Initial emission needs a rule in the reverse translator. |
| E9 | Between-tick state: `Clock._tick`, `Intervention._elapsed/_frozen`, the consumer-resource internal state, the OpenCOR wrapper's own time; the roadrunner wrapper keeps one instance, pushes the incoming species values and simulates from its current time; the COMETS wrapper sub-steps `ceil(interval / time_step)` cycles inside one update. | viva-basic-processes, crm-fba, viva-opencor, viva-tellurium, viva-comets | G5, P5 | All explicit state or restart semantics; P5 not needed.  The reverse translator needs per-class knowledge. |
| E10 | Threshold-driven `_add`/`_remove` of dFBA species (new ones inherit the parent's interval), and particle division at a mass threshold. | cdFBA `dfbalauncher.py`; spatio-flux reference, particles, comets composites | G6 | Recommendation stands; bounded forms are a masked Scatter.  Absent from the 68-document corpus (an earlier note that two corpus documents contain removal was wrong: the match was the config key `atoms_to_remove`). |
| E11 | The Ray shard manager takes over a whole tick through the engine's `tick_lifecycle` hook: it reads the fields once, calls the actors in parallel and adds the results by direct array writes, skipping the reconcile step; it states that this is valid only for the spatio-flux wiring. | spatio-flux `library/shard_manager.py`; process-bigraph `composite.py` | G2, P1 | Holds: snapshot-and-add is the practised semantics.  Do not infer semantics from runtime hooks. |
| E12 | Emitters are time-triggered steps that observe at every tick of the finest interval and always include `global_time`.  `RunProcess` and `ParameterScan` steps host an inner simulation for `runtime` at `timestep` and return a series with `runtime / timestep + 1` points. | process-bigraph `emitter.py`, `processes/parameter_scan.py` | Reports, G1 | Report rows are per finest tick, as the Loop output already is.  `RunProcess` and `ParameterScan` map to a SED2 time course and a ParameterScan, not to a clock loop. |
| E13 | Time precision is the number of decimal digits in the string form of the step (`interval_time_precision`). | process-bigraph `composite.py` | P2 | **Changed:** periods and windows evaluated in exact decimal arithmetic. |
| E14 | The maintainers pin the multi-rate timing contract (their issue 234): a process reads its inputs at the **start** of its interval and the delta is applied at the **end** (the "stash" model of S1 3.8.6), not the read at the event time of S1 3.8.2; the two agree only when intervals are equal.  The test uses intervals 1 and 2 and expects x = 0.25, y = 0.25 after t = 2, the same numbers as the measurement in section 2. | process-bigraph `tests/test_multirate_scheduling.py` | G1, P2 | **Settles the open point** noted in section 2 and in G1: P2's stale-read rule is the maintainers' own contract, not just the implementation. |
| E15 | A spec-built composite derives `global_time_precision` from the decimal digits of its intervals (a 0.1 grid gives precision 1; intervals 0.1 and 0.25 do not share a grid and get no automatic default), and a test requires `global_time` to be exactly 0.0, 0.1, ..., 3.0 rather than a drifting float sum. | process-bigraph `process_bigraph/tests/test_composite_spec.py` | P2 | Supports exact decimal arithmetic for `every`, `period` and `window`. |

### Proposal status after the evidence

| Proposal | Status | Basis |
|---|---|---|
| P1 | Kept, optional; gains the "no change" rule | E3, E11 |
| P2 | Kept, **revised** (window, step length, skip rule, decimal arithmetic) | E1 to E5, E13 |
| P3 | Kept; rationale is SED2-side (stochastic stepping, converged iterations) | E6, E8 |
| P4 | Deferred; the one use case does not need it | E6, E7 |
| P5 | Deferred; stochastic only | E9 |
| P6, P7 | Not proposed; G6 recurs (E10) but stays out, with the bounded-form refinement | E10 |

### What to record per document (phase R1 of the reverse plan)

For each process-bigraph document read in R1, one row, so that this log is extended from counts:

| Item | Why |
|---|---|
| Intervals of all processes: single, integer multiples, or common tick only (exact decimal; the tool also records the tick and each `every`) | G1, P2 |
| Process classes with hidden state (known mapping or not) | G5, E9 |
| `calculate_timestep` overridden; any Step wired to a process's `interval` | G3, E6 |
| Time windows or time-gated config (`window`, `use_global_time`) | P2 window, E3 |
| A Step that reads an interval or elapsed time | `.step`, E5 |
| Equal-interval processes sharing a store (and its type: add or overwrite) | G2, P1 |
| `_add`, `_remove`, `_divide` and whether the candidates or a cap are known | G6, E10 |
| Run driver: literal duration, count times interval, or a condition; `run(0.0)` | G4, P3, E8 |
| Steps with no process upstream (fire once at the start) | G8 |
| `parallel_processes` or runtime hooks present | E11 |

Review points: at the end of R1 (counts into this log; each proposal's status re-checked against them) and at R6 (the proposal file for `SED2/TODO.md` is written from the log, not from this file's first draft).

## Sources

* Agmon and Spangler, arXiv:2512.23754v2, main text and Supplements S1 (sections 3.5, 3.8) and S2 (DynamicFBA).
* process-bigraph 1.8.5 (git e5325c1): `process_bigraph/composite.py` (`Process`, `Step`, `calculate_timestep`, `run`,
  structural sentinels), `process_bigraph/processes/` (`simulation.py`, `parameter_scan.py`, `dynamic_structure.py`,
  `growth_division.py`, `reaction.py`, `bigraphical_reactive_system.py`), `docs/tick_lifecycle.md`,
  `docs/architecture.md`: https://github.com/vivarium-collective/process-bigraph
* SED2 specsheets read: `tasks/Loop`, `tasks/Repeat`, `tasks/NumericRange`, `tasks/ModelChange`,
  `tasks/FluxBalanceAnalysis` (v1.0.0).
* The cosimulation document supplied by the SED2 author (earlier syntax), analysed in `process-bigraph.md`, 5.1.
* Evidence review (section 8): vivarium-collective clones of cdFBA, crm-fba, process-bigraph (`scripts/corpus/legacy_documents.json`, `experiments/minimal_gillespie.py`, `processes/parameter_scan.py`, `composite.py`), spatio-flux (`library/shard_manager.py`, composites), viva-basic-processes (`clock.py`, `tick.py`, `intervention.py`), viva-biomodels, viva-comets, viva-copasi, viva-opencor, viva-tellurium, vivarium-cobra; SED2 `SPECIFICATION.md` (`OneStepStochasticSimulation`, Loop and Repeat outputs).
* Experiments: see `process-bigraph.md`, section 2.9 (flat versus hosted clock, parallel versus sequential coupling,
  stale reads at different intervals, init firing, object loop variables).
