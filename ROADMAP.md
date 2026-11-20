# Roadmap

## v0.1.x · Keep the example reproducible

- Maintain the offline RIVM case, the source and extract checksums, the independent pixel counts, and the type-valid failure case.
- For corrections, record the changed input or assumption, regenerate the reference, and check the cited release remains reproducible from its tag.

## v0.2 · CRS-aware backend (released)

- The optional backend runs `Constrain`, `Coverage` and `Proportion` on north-up rasters and polygon boundaries in a shared projected metre CRS.
- Fractional cell areas contribute to the whole-zone share. Missing raster support, mismatched CRS and ambiguous transforms raise errors.
- CI checks parity on aligned windows, boundary and hole geometry, nodata, and three CBS neighbourhood results against a GDAL reference. The offline example remains in the test matrix.

## v0.3 · Evaluate answers and ranking

- Publish a small set of benchmark questions with pinned inputs and independent reference outputs. Include wrong-threshold, wrong-support and missing-denominator cases.
- Report type admissibility, numerical correctness, and execution time separately. Track how often an admissible workflow gives the wrong answer.
- Use [GeoQA Study Harness](https://github.com/daudee215/geoqa-study-harness) to ask analysts to rank a shared set of candidate workflows. Report inter-analyst agreement, Kendall's tau between the cost model and analyst orderings, and the pairs that disagree. Use the disagreements to design the next ranking changes.

## v0.4 · Expand the question and ontology interfaces

- Add controlled question forms based on the benchmark. Test ambiguous wording, missing units, and requests outside the supported operations.
- Compare asserted type relations with the closure from an OWL reasoner and document any differences that affect workflow admission.
- Publish the new evaluation alongside the v0.3 results so readers can see which requests and execution cases changed.
