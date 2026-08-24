# typed-workflow-layer

A small, runnable implementation of a typed intermediate layer for geo-analytical
question answering, by M. Daud Tasleem.

Python 3.10, standard library only. No numpy, no geopandas, no external packages.

```
python3 demo.py
python3 -m unittest discover -s tests
```

Both run on a clean machine from this directory. The demo prints about two hundred
lines and takes a second.

## What it is

Datasets are annotated with core concept data types. A transformation declares which
types it consumes and which type it produces. From a set of typed sources and a target
type, the package enumerates every workflow that reaches the target within a depth
bound, refuses the ones that do not type check, explains each refusal, and emits a
self-describing conceptual transformation graph for each workflow it does return.

The worked example is the proportion of area covered
by at least 70 dB of noise for each district in Amsterdam, from a noise contour map
and a set of district boundaries.

The single idea worth taking away is in `Coverage`. Measuring how much of a field falls
inside an object moves the value from the field to the object and makes it an extensive
quantity: covered areas over disjoint districts add up. A proportion or a mean is
intensive and does not. Both are ratio scaled, so Stevens' scales alone cannot separate
them, and a system that does not separate them will happily sum a column of percentages.
`ExtensiveQuantity` and `IntensiveQuantity` are distinct subtypes of `Ratio` for that
reason, and almost everything the package refuses, it refuses on that axis or on the
core concept axis.

## What it is not

It is not a GIS. It does not read geodata, does not project anything, and does not
execute a workflow against real data. The only geometry in the repository is a handful
of integer rectangles inside `demo.py`, so that the last section of the demo prints
numbers that came from an actual computation rather than from nowhere. The point being
demonstrated is the typing, not the geometry.

It is not a question answering system. `request.py` recognises three fixed phrasings and
raises on everything else. There is no natural language step anywhere, and the demo says
so at the point where a human transcribes the question by hand.

It is not the CCD ontology. It is a readable approximation of the part of it that does
the work described below.

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
   refusals shown here and it can be read in a few minutes.

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
   comments explaining what is being assumed. `Overlay` in particular cannot express
   that its two slots must share a support, because the componentwise model has no way
   to say that two slots agree.

8. **Three search restrictions**, all marked in `synthesis.py` as heuristics rather than
   claims about geography: distinct datasets across slots, no transformation applied to
   a dataset it produced itself, and every step must contribute to the final output.

## Limits

Read this section before the code.

- **Toy geometry.** Axis aligned integer rectangles, assumed disjoint, intersected with
  four comparisons. No CRS, no projection, no topology, no validity checking. The
  library contains no geometry at all.
- **No execution.** Nothing here runs against real geodata. A synthesised workflow is a
  graph of names and types. Binding each name to a real operation is the next piece of
  work and it is not started.
- **A tiny catalogue.** Ten transformations. The CCD work covers a far larger operation
  set, and several signatures here would be argued over.
- **No CNL.** Three fixed phrasings and a regular expression. The transcription from the
  English question to the controlled phrasing is done by a human in `demo.py`.
- **Depth-bounded search.** The demo runs at depth 4. Nothing here says what happens at
  depth 8, and the counts printed in section 4 suggest it grows quickly.
- **No cost model.** The 24 admissible workflows are returned unranked. Some are sensible
  and some are absurd, and the package has nothing to say about which is which.
- **No support checking between slots.** `Overlay` accepts two fields with different
  supports. That is a real hole and it is left open rather than papered over.
- **No treatment of Network or Event.** Both terms exist on the concept axis and no
  transformation in the catalogue uses either.
- **The type layer proves admissibility, not correctness.** A workflow that type checks
  can still be the wrong answer to the question asked. That is the honest boundary of
  the whole approach and it is why the constraint mechanism in `request.py` exists.

## What I would build next, in order

1. Bind each catalogue entry to a real operation, one GDAL or QGIS processing algorithm
   per transformation, so a synthesised workflow can be run and its output compared with
   a hand written reference at the level of the operation graph.
2. Replace the componentwise axes with the published CCD ontology, loaded from OWL and
   checked with a reasoner, keeping the current model as a fast pre-filter.
3. Add ranking over the enumerated set. Cost, data availability and a preference for
   workflows that consume every named source would remove most of the absurd ones
   without touching the type layer.
4. Replace the controlled phrasing with a question interface that emits a target type
   and a set of constraints rather than emitting code, so that whatever produces it,
   a grammar or a language model, is still checked by the same layer.
5. Move provenance to PROV-O. The graph already carries an entity, an activity and a
   derivation, so this is a change of writer rather than a change of model.

## Files

| file | what it holds |
| --- | --- |
| `ccd.py` | the three axes, subsumption, unification, and the mismatch report |
| `catalogue.py` | ten typed transformations and the repair suggestion facility |
| `synthesis.py` | enumeration of all valid workflows, and `why_rejected` |
| `provenance.py` | the conceptual transformation graph, JSON and text tree |
| `request.py` | three controlled phrasings to a target type plus constraints |
| `demo.py` | the Amsterdam example, two refusals, and the toy geometry |
| `tests/` | 78 unittest cases, one file per module, including a run of the demo |

## Licence

MIT. See `LICENCE`.
