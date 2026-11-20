# typed-workflow-layer

[![tests](https://github.com/daudee215/typed-workflow-layer/actions/workflows/tests.yml/badge.svg)](https://github.com/daudee215/typed-workflow-layer/actions/workflows/tests.yml)

A small, runnable implementation of a typed intermediate layer for geo-analytical
question answering, by M. Daud Tasleem.

It is the middle of three packages written to work together. Attributes are
annotated and the annotation agreed on in
[geo-annotation-kit](https://github.com/daudee215/geo-annotation-kit), which produces the
typed sources this package consumes; the answers this package's workflows produce are
put in front of people and scored in
[geoqa-study-harness](https://github.com/daudee215/geoqa-study-harness).

Python 3.10 or later. The core and the worked examples use the standard library.

## Amsterdam road-noise example

*What share of each selected Amsterdam window is mapped in an Lden road-noise
class of 70 dB or higher?* Run this from the repository root:

```bash
python -m examples.amsterdam_noise
```

The example runs offline on a frozen extract of RIVM's 2022 modelled road-noise
raster. The reference counts qualifying 10 m raster cells directly. The
workflow measures their area using `Constrain → Coverage → Proportion`. A second
workflow omits `Constrain`, produces the same declared output type, and returns
the share covered by the input raster. The reference catches the difference.

| Window | Pixels at or above 70 dB | Reference and thresholded workflow | Unfiltered workflow |
| --- | ---: | ---: | ---: |
| West | 425 / 900 | 47.22% | 100% |
| Central | 0 / 900 | 0.00% | 100% |
| South | 611 / 900 | 67.89% | 100% |

Both workflows execute. The thresholded workflow matches all three reference
values, and the unfiltered workflow fails all three comparisons.
`python -m examples.amsterdam_noise --json` prints the checks and execution
traces.

The windows are three 300 m squares chosen to illustrate different levels of
coverage. Their results describe mapped road-noise classes within those squares.
See the [input provenance and regeneration guide](examples/data/amsterdam_noise/README.md),
[reference counts](examples/data/amsterdam_noise/reference.json), and
[citation metadata](CITATION.cff).

## Core implementation

The repository now contains a complete, reproducible vertical slice: a typed
workflow can be bound to runtime values, executed by a rectangle backend,
checked against a reference output, and exported with PROV-O relations. The
backend is intentionally small; it is an experiment seam for a future
CRS-aware GIS adapter, not a claim to replace one.

The type lattice is an OWL ontology, `typed_workflow_layer/ontology/ccd.ttl`. `owl.py` reads it at import
and `ccd.py` builds the subsumption relation from its rdfs:subClassOf axioms, so the
hierarchy is data a reasoner can read rather than a dict only this package understands.
The reader is a few hundred lines of standard library covering the Turtle subset the
ontology uses; rdflib is not required to run it, and is used instead as a cross-check
that the two parsers return the same triples (`pip install '.[check]'`).

```
python3 demo.py
python3 -m unittest discover -s tests
```

Both run on a clean machine from this directory. The demo prints about 280 lines and
takes a second.

## What it is

Datasets are annotated with core concept data types. A transformation declares which
types it consumes and which type it produces. From a set of typed sources and a target
type, the package enumerates every workflow that reaches the target within a depth
bound, refuses the ones that do not type check, explains each refusal, and emits a
self-describing conceptual transformation graph for each workflow it does return.

The original `demo.py` uses synthetic rectangles to demonstrate the question
of how much of each district is covered by noise of at least 70 dB.

The single idea worth taking away is in `Coverage`. Measuring how much of a field falls
inside an object moves the value from the field to the object and makes it an extensive
quantity: covered areas over disjoint districts add up. A proportion or a mean is
intensive and does not. Both are ratio scaled, so Stevens' scales alone cannot separate
them, and a system that does not separate them will happily sum a column of percentages.
`ExtensiveQuantity` and `IntensiveQuantity` are distinct subtypes of `Ratio` for that
reason, and almost everything the package refuses, it refuses on that axis or on the
core concept axis.

## Ranking

Type checking says a workflow may run. It does not say which of the admissible workflows
anybody should run. `cost.py` and `ranking.py` answer that, and every term is read off the
same CCD axes the checker already uses rather than invented alongside them:

- **scale loss**, descent through Stevens' measurement scales, which the quality lattice
  in `ccd.py` already orders
- **support loss**, coarsening of the geometry a value is defined over
- **concept shift**, a change of core concept, which is a modelling decision
- **length**, as a tiebreaker only
- **source**, from declared resolution and currency, bounded so it never dominates
- **redundancy**, computations performed twice

Two claims in there are worth arguing with. The first is **position weighting**: a loss at
the first step costs more than the same loss at the last, because everything downstream is
computed from what survived. Constrain then ZonalStatistics and ZonalStatistics then
Constrain type check identically, and the second is the better workflow because the
statistics saw the values. Position weighting is the only thing separating them.

The second is that **weights are policy**. They sit in a dataclass with stated defaults,
`CostModel.with_weights` produces variants, and `ranking.stability` reports how much of
the ordering survives each weight doubled and halved. On the noise question the winner
holds across all twelve variants, which makes it a claim about the workflows. Had it
moved, that would have been a claim about the weights, and the difference is measurable
rather than asserted.

`ranking.plan` exists because `Workflow.expression` flattens a directed acyclic graph into
a tree, so a shared intermediate prints once per consumer and the workflow reads as doing
the work twice. Of the 176 workflows at depth four, 47 share an intermediate and are
misread this way. None of them genuinely recomputes anything: since the search started
keeping the shortest realisation of an expression, the workflow that computes a shared
subexpression once is always shorter than the one that computes it twice and always wins
the key, so the enumerator cannot emit the second kind at all. Reading as redundant and
being redundant remain different things, which is why there is both a `sharing` report and
a `redundancy` cost, but the cost is now a check on chains arriving through `build_chain`
rather than something that separates enumerated candidates. The same fact arrives from the
cost side under "Whether the ranking is doing any work" below: `redundancy` is one of three
components that never vary on this scenario, so its weight is inert here at any value.

## Execution, provenance and correctness

`executor.py` is the runtime seam. `RuntimeDataset` keeps the declared CCD
type beside each payload, `validate_workflow()` checks the workflow structure
and inferred types before any backend call, and `ExecutionResult.records`
records every input, output, type and parameter used. The bundled
`RectangularBackend` implements
`Constrain`, `Clip`, `Coverage`, `ZonalStatistics`, `Aggregate`, `Proportion`,
`Reclassify`, `Buffer` and `Overlay` over validated axis-aligned rectangles.
Unsupported operations fail explicitly instead of silently producing a fake
answer. `ExecutionResult.fingerprint` provides a deterministic SHA-256 digest
of the runtime trace and output, so repeated runs can be checked or cached.
Coverage also computes rectangle union area, avoiding double-counting when
input contours overlap.

The backend is deliberately replaceable. A production adapter can implement
the same `Backend.run()` contract for GeoPandas, PostGIS, GDAL or QGIS while
leaving the type checker and search unchanged. This separation is useful for
the PhD workflow: semantic admissibility, execution, and empirical correctness
are measurable as separate claims.

`evaluation.py` compares an execution result with a reference value, reporting
missing keys, unexpected keys, absolute error and relative error. This makes a
type-valid but numerically wrong workflow visible. `provenance.py` retains the
compact CTG JSON format and now also exports PROV-O-shaped JSON and deterministic
Turtle with `prov:Entity`, `prov:Activity`, `prov:used`,
`prov:wasGeneratedBy` and `prov:wasDerivedFrom` relations.

Run the executable worked example with:

```
python demo.py
```

The demo now prints the executed steps and the reference-comparison result in
addition to the type-synthesis and ranking evidence.

## Measuring the search instead of asserting things about it

The three search restrictions in `synthesis.py` each arrived with a comment explaining why
they were harmless, and a comment is not evidence. `analysis.py` turns each one off, runs
the search again, and reports what comes back. Run it with `python3 analysis.py`.

It found two defects and retired one restriction.

**The workflow cap truncated silently.** `enumerate_workflows` stopped at `max_workflows`
and returned a plain list, so a capped result was indistinguishable from a complete one. A
caller ranking those workflows would have been ranking an arbitrary prefix of the space
while believing it had all of it. The result is now a list carrying `.stats.truncated`. At
the depth the demo uses the default cap of 500 is not binding, 176 workflows; one level
deeper there are 1,259 and it would have been.

**The search kept the wrong realisation of an expression.** `expression()` renders a
workflow as a tree while the workflow is a DAG, so a step feeding two later steps is
printed twice. Two different step lists can therefore render identically: one computing a
shared subexpression once, one computing it twice. Both are correct and one is a step
longer. The deduplication kept whichever the search reached first, which was the longer one
for 2 of the 176 workflows, and `cost.py` charges length from `len(workflow.steps)`, so
those two were ranked worse for steps they did not need. It now keeps the shortest.

That fix then made the `connected` restriction obsolete. A workflow carrying a step that
feeds nothing is strictly longer than the same expression without it, so it can no longer
win the key. `connected` is now provably a no-op on both the expression set and the stored
objects, and is kept as a flag only so the suite keeps checking that.

### What the search actually costs

| depth | candidates | type checks | workflows | seconds |
| --- | --- | --- | --- | --- |
| 1 | 20 | 20 | 1 | 0.000 |
| 2 | 272 | 257 | 5 | 0.001 |
| 3 | 4,736 | 4,258 | 28 | 0.012 |
| 4 | 111,876 | 96,802 | 176 | 0.271 |
| 5 | 3,456,516 | 2,902,739 | 1,259 | 8.248 |

The growth factor is not constant, it rises: 13.6, 17.4, 23.6, 30.9. Each step adds a
dataset to the pool and two-slot transformations draw ordered pairs from it, so the
branching grows with depth rather than staying fixed. Depth 5 is about the practical
ceiling on one core.

### Why a depth bound is defensible

The type closure saturates after one round. Five core concept data types are reachable from
these two sources and nothing new appears after that, while the workflow count is still
multiplying by thirty per level. Almost everything a deeper search finds is another route
to a type that was already reachable.

That is the argument for bounding depth, and it is also the argument for having a cost
model at all: past the fixpoint the search stops adding capability and starts adding
alternatives, so something has to order them.

Of the ten catalogue entries, nine appear in some workflow reaching this target.
`Interpolate` never does, because it needs point support and the noise source is region
support. That is a fact about this question, not a fault in the catalogue.

### Whether the ranking is doing any work

Reported rather than hidden. The 176 workflows collapse into 32 distinct scores, the
largest tie group holds 22, and rank 1 is a two-way tie. A rank of 1 drawn from a tie is
not a winner, and the analysis says so instead of printing a leaderboard.

Three of the six cost components never vary across this scenario at all: `support_loss`,
`source` and `redundancy`. Their weights are inert here at any value, so the order is
decided by the three that do vary, and tuning one of the inert three to fix a ranking would
be wasted effort. `redundancy` is inert for a specific reason: the enumerator can no longer
emit a workflow that recomputes anything, so the term is zero on every candidate. It still
earns its place, because `build_chain` accepts chains from outside the search and those are
where recomputation arrives.

Perturbing each weight by 25 per cent on its own leaves the top workflow unchanged in all
12 trials, the top-five set unchanged in 10, and Kendall's tau against the unperturbed
order between 0.962 and 1.000. The first of those three numbers alone would have been
misleading, because ties are broken on the expression string and an unchanged top can mean
the tie-break did not move rather than the model did not. The three inert components give
tau of exactly 1.000, which is the component-variance measurement and the perturbation
measurement agreeing independently.

## What it is not

It is not a production GIS. It does not read shapefiles or databases, manage CRS
transformations, validate polygon topology, or execute against real Amsterdam data. The
bundled rectangle backend is a deterministic test and research backend, so the demo
prints values from an actual execution while keeping its geometry assumptions explicit.

It is not a general question answering system. `request.py` keeps a strict controlled
parser and additionally offers `parse_question()` for a few explicit English surface
forms. It still raises on unsupported wording and returns a typed request rather than
generating code.

It is not the published CCD ontology. `typed_workflow_layer/ontology/ccd.ttl` is an OWL ontology written for
this package: seventeen classes over three axes, with the modelling arguments carried as
rdfs:comment next to the axiom each one justifies. It approximates the part of the
published ontology that does the work described below.

## Theory

Two papers, both real.

- Scheider, S., Meerlo, R., Kasalica, V., Lamprecht, A.-L. (2020). Ontology of core
  concept data types for answering geo-analytical questions. *Journal of Spatial
  Information Science* 20, 167-201. doi:10.5311/JOSIS.2020.20.555
- Kruiger, J.F., Kasalica, V., Meerlo, R., Lamprecht, A.-L., Nyamsuren, E.,
  Scheider, S. (2021). Loose programming of GIS workflows with geo-analytical concepts.
  *Transactions in GIS* 25(1). doi:10.1111/tgis.12692

The first supplies the type system: core concepts after Kuhn, a measurement axis and a
support axis, with meaningfulness of a computation decided by the types rather than by
the operator's intuition. The second supplies the reason for enumerating rather than
planning: once concepts constrain the search, a workflow can be assembled from a loose
specification, and the interesting output is the set of admissible assemblies rather
than one of them.

## Design decisions

1. **The three axes are compared componentwise** rather than flattened into named
   composite types. This is weaker than the published ontology: it cannot say that some
   combinations of concept, quality and support are meaningless. It is enough for the
   refusals shown here. The cost is a constraint the loader enforces rather than assumes:
   each axis has to be a single chain, so a class declaring two superclasses raises at
   import instead of quietly changing what subsumes what.

2. **The scale hierarchy runs from nominal down to ratio.** A slot that asks for
   `Nominal` accepts a ratio-scaled field, because the extra structure can always be
   ignored. This is why `Coverage` applies to an unthresholded noise field as well as to
   a thresholded one, and why the demo needs a constraint rather than a type to rule
   that out.

3. **Extensive and intensive are separated under `Ratio`.** See above. `Aggregate`
   accepts only extensive quantities. `Proportion` is the step that converts one into
   the other, and it is the reason the target type of a proportion question is
   `Object(IntensiveQuantity, RegionSupport)` and not the extensive covered area.

4. **Enumeration returns everything, not the first hit.** The object of interest is
   the set of possible valid ways to address a question, so `enumerate_workflows`
   returns all of them, ordered shortest first and deduplicated by their expression.

5. **A request carries constraints as well as a target type.** A threshold in the
   phrasing forces a `Constrain` step into every candidate. Without it, enumeration
   returns workflows that compute a share of total area and never look at the threshold.
   Those workflows type check. They answer a different question. Type validity is
   necessary and not sufficient, and the demo prints the counts that show it: at depth 4
   the Amsterdam target is reached by 176 workflows, of which 24 honour the constraint.

6. **Rejection is a first-class output.** `why_rejected` names the step, the slot, each
   failing axis, and which catalogue entries would repair the gap. A type checker that
   only says no is a type checker nobody keeps.

7. **Signatures that are debatable say so.** `Aggregate`, `Buffer` and `Overlay` carry
   comments explaining what is being assumed. `Overlay` now adds an explicit cross-slot
   support constraint, so fields on point and region supports cannot be combined silently.

8. **Three search restrictions**, all marked in `synthesis.py` as heuristics rather than
   claims about geography: distinct datasets across slots, no transformation applied to
   a dataset it produced itself, and every step must contribute to the final output.

## Limits

Read this section before the code.

- **Geometry and CRS.** The bundled backend uses pre-aligned, axis-aligned
  rectangles. The RIVM example binds native grid cells in a single projected CRS.
  Polygon geometry, reprojection and mixed-CRS input are future backend work.
- **A tiny catalogue.** Ten transformations. The CCD work covers a far larger operation
  set, and several signatures here would be argued over.
- **Small question surface.** Three controlled phrasings plus a few explicit
  English forms are supported. This is not open-ended natural-language
  understanding and does not infer missing datasets or units.
- **Depth-bounded search.** The demo runs at depth 4. Nothing here says what happens at
  depth 8, and the counts printed in section 4 suggest it grows quickly.
- **The cost model has no gold standard behind it.** `cost.py` ranks the 24 admissible
  workflows and `ranking.stability` shows the winner holds across every weight doubled
  and halved, twelve variants. What has not been done is collecting an ordering from
  analysts and measuring against it. `ranking.agreement` computes Kendall's tau and
  `ranking.disagreements` names the flipped pairs, so the check is implemented and
  unrun. Until it is run, the ranking is a defensible model rather than a validated one.
- **Cost weights are policy.** The six weights in `cost.Weights` were chosen so that one
  scale descent early outranks any plausible difference in length. That is an argument,
  not a measurement, and it is why the sensitivity facility exists.
- **Support checking is explicit but limited.** `Overlay` now rejects fields
  with different supports. More complex relations, such as partition and
  topology constraints, still need a richer constraint language.
- **No treatment of Network or Event.** Both terms exist on the concept axis and no
  transformation in the catalogue uses either.
- **Reference coverage.** `evaluation.py` checks the synthetic demo and the
  three RIVM windows. A broader evaluation needs independent reference outputs
  across questions, perturbation tests, and analyst review.

## Next versions

The [roadmap](ROADMAP.md) sets out the CRS-aware backend, a benchmark for
answers and ranking, and later work on the question interface and OWL entailment.

## Files

| file | what it holds |
| --- | --- |
| `typed_workflow_layer/ontology/ccd.ttl` | the type lattice as OWL: seventeen classes, three axes, annotated |
| `owl.py` | a dependency-free Turtle reader, and the subsumption relation it builds |
| `ccd.py` | the three axes, subsumption, unification, and the mismatch report |
| `catalogue.py` | ten typed transformations and the repair suggestion facility |
| `synthesis.py` | enumeration of all valid workflows, and `why_rejected` |
| `provenance.py` | the conceptual transformation graph, CTG JSON, PROV JSON and Turtle |
| `request.py` | controlled phrasings and a small English surface to typed requests |
| `executor.py` | runtime validation, backend contract, rectangle execution and traces |
| `evaluation.py` | reference comparison with absolute and relative error reporting |
| `cost.py` | scale, support, concept, length, source and redundancy cost, position weighted |
| `ranking.py` | ordering, pairwise explanation, plan rendering, Kendall's tau, sensitivity |
| `demo.py` | the Amsterdam example, two refusals, the toy geometry, and the ranking |
| `examples/amsterdam_noise.py` | offline execution and reference checks on the RIVM raster extract |
| `analysis.py` | soundness, growth, ablation, type closure, ranking discrimination |
| `tests/` | regression, execution, provenance, evaluation and demo tests |

## Licence

MIT. See `LICENCE`.
