# Workflow benchmark v0.3

The benchmark tests 21 fixed candidates on 10 questions. It includes workflows
that return the requested answer, workflows that type-check and give a different
answer, and workflows with a specified refusal. This is a controlled diagnostic
set with deliberately selected failure cases.

From a source checkout in a virtual environment, run:

```bash
python -m pip install ".[gis]"
python -m examples.workflow_benchmark
python -m examples.workflow_benchmark --json --timing
```

The first run prints a scorecard. JSON includes each candidate's output and
diagnostic. Optional timings are per-candidate wall-clock times around execution,
including runtime validation. They exclude fixture loading, candidate construction,
and reference comparison. Omit `--timing` for a reproducible JSON report.

| Measure | Verified result |
| --- | ---: |
| Type-admitted candidates | 19 / 21 |
| Numerical matches among returned answers | 9 / 17 |
| Type-admitted wrong answers | 8 |
| Correct refusals on refusal questions | 3 / 3 |
| Candidate outcomes matching the declared outcome and any refusal reason | 21 / 21 |

The numerical denominator counts returned answers on seven questions with
numeric references. These questions have 18 candidates, one of which is refused
because it returns a share where the question asks for square metres. The
refusal denominator covers the three questions whose reference is a refusal.
For refusals, both stage and reason must match. The scores describe these fixed
candidates and include the designed controls.

## Inputs and independent references

[questions.json](questions.json) pins the public input files with SHA-256
checksums and includes the synthetic inputs, candidate predicates, and expected
outcomes. The JSON report identifies this exact benchmark by its own checksum.

- The [RIVM rectangle fixture](../amsterdam_noise/README.md) uses direct pixel
  counts divided by 900. The qualifying counts are 425, 0, and 611 at or above
  70 dB, 185, 0, and 263 at or above 75 dB, and 475, 900, and 289 below 70 dB.
- The [CBS neighbourhood fixture](../amsterdam_polygons/README.md) uses the
  independent GDAL fractional zonal reference from v0.2.
- The small synthetic references use hand calculations. The strip has three
  equal 100 m² cells, two at or above 70 dB. For the fractional polygon, the
  qualifying area is 1.5 m² and the area after subtracting its hole is 2.75 m².
- The refusal cases cover point interpolation applied to regional cells,
  insufficient valid raster area for a whole-zone share, and mismatched
  projected coordinate reference systems.

## Analyst ranking

The [blinded task file](study_tasks.json) loads directly in
[GeoQA Study Harness](https://github.com/daudee215/geoqa-study-harness).
It asks analysts to order the same four candidates on each of two benchmark
questions. It shows the expression and its bound threshold, with scores and
reference answers withheld from the packet. Generate a readable copy with
`python -m examples.benchmark_study packet`.

1. Give each analyst the same task file or the generated packet. Ask them to rank
   independently for suitability to the question as written. Ties are allowed.
2. Use the Harness to collect responses and export the consent-filtered results.
   The comparison reads `tasks.json` and `responses.csv` from that export. Each
   answer is a JSON list of rank groups, best first, with one occurrence of
   every label shown for the task.
3. Run `python -m examples.benchmark_study compare /path/to/export` from this
   checkout. The report uses complete ballots and states how many are incomplete.
   It reports Kendall's tau-b and strict preference reversals per task, for
   model–analyst and analyst–analyst pairs, with participant codes omitted.

The cost model ranks workflow structures, so candidates with the same structure
and different thresholds share a model rank. The comparison keeps these ties.
When a ranking provides no ordered pairs to estimate agreement, tau-b is
reported as null. Use the pair-level results to decide whether a disagreement
comes from the workflow structure or its parameter binding before changing weights.

**Study status.** The task file and comparison are ready. Analyst agreement
awaits collected responses.
