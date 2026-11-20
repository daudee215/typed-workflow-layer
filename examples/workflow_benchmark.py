"""Score fixed workflow candidates against independent answers and refusals."""

import argparse
import hashlib
import json
from pathlib import Path
from time import perf_counter

import ccd
from evaluation import compare
from examples.amsterdam_noise import SOURCES, THRESHOLDED, UNFILTERED, bind_grid, load_inputs
from executor import ExecutionError, RuntimeDataset, execute
from synthesis import build_chain


QUESTIONS = Path(__file__).resolve().parent / "data" / "workflow_benchmark" / "questions.json"
CHAINS = {
    "share": THRESHOLDED,
    "unfiltered": UNFILTERED,
    "area": THRESHOLDED[:2],
    "interpolate": (("Interpolate", ("noise",)),),
    "clipped-share": (
        ("Clip", ("noise", "zone")),
        ("Constrain", ("$0",)),
        ("Coverage", ("$1", "zone")),
        ("Proportion", ("$2",)),
    ),
}
TARGETS = {
    "share": ccd.CCDType(ccd.OBJECT, ccd.INTENSIVE, ccd.REGION_SUPPORT),
    "area": ccd.CCDType(ccd.OBJECT, ccd.EXTENSIVE, ccd.REGION_SUPPORT),
    "field": ccd.CCDType(ccd.FIELD, ccd.INTERVAL, ccd.REGION_SUPPORT),
}


def load_benchmark() -> tuple[dict, str]:
    raw = QUESTIONS.read_bytes()
    benchmark = json.loads(raw)
    for relative_path, expected in benchmark["snapshots"].items():
        data = (QUESTIONS.parent.parent / relative_path).read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError(f"Snapshot hash mismatch: {relative_path}")
    return benchmark, hashlib.sha256(raw).hexdigest()


def admit(case: dict, candidate: dict):
    workflow = build_chain(CHAINS[candidate["chain"]], SOURCES)
    target = TARGETS[case.get("target", "share")]
    if not target.subsumes(workflow.result.type):
        raise TypeError(f"requested result type {target}, but candidate returns {workflow.result.type}")
    return workflow


def fixture(name: str, synthetic: dict):
    if name == "rivm-grid":
        grid, _ = load_inputs()
        return bind_grid(grid), None
    if name == "cbs-polygons":
        from examples.amsterdam_polygons import load_inputs as load_polygons
        from typed_workflow_layer.gis_backend import RasterPolygonBackend

        raster, zones, _, _ = load_polygons()
        return (RuntimeDataset("noise", SOURCES[0].type, raster),
                RuntimeDataset("zone", SOURCES[1].type, zones)), RasterPolygonBackend()

    data = synthetic[name]
    if data["backend"] == "rectangle":
        return (RuntimeDataset("noise", SOURCES[0].type, data["fields"]),
                RuntimeDataset("zone", SOURCES[1].type, data["zones"])), None

    import numpy as np
    from rasterio.transform import from_origin
    from shapely.geometry import Polygon

    from typed_workflow_layer.gis_backend import PolygonZones, RasterField, RasterPolygonBackend

    raster = RasterField(np.array(data["values"], dtype=float),
                         from_origin(*data["origin"], 1, 1), data["crs"])
    zones = PolygonZones(
        tuple((identifier, Polygon(**geometry)) for identifier, geometry in data["zones"]),
        data.get("zone_crs", data["crs"]),
    )
    return (RuntimeDataset("noise", SOURCES[0].type, raster),
            RuntimeDataset("zone", SOURCES[1].type, zones)), RasterPolygonBackend()


def evaluate_candidate(case: dict, candidate: dict, inputs, backend, timing: bool) -> dict:
    row = {"question": case["id"], "candidate": candidate["id"],
           "expected": candidate["expect"], "type_admitted": False}
    reference = case["reference"]
    expected_refusal = candidate.get("refusal", reference.get("refusal", {}))
    try:
        workflow = admit(case, candidate)
    except TypeError as error:
        row.update(outcome="type_refusal", diagnostic=str(error))
    else:
        row["type_admitted"] = True
        row["expression"] = workflow.expression()
        parameters = {"Constrain": candidate["predicate"]} if "predicate" in candidate else None
        if parameters:
            row["parameters"] = parameters
        start = perf_counter()
        try:
            result = execute(workflow, inputs, backend=backend, parameters=parameters)
        except ExecutionError as error:
            row.update(outcome="execution_refusal", diagnostic=str(error))
        else:
            row["outcome"] = "unexpected_answer"
            if "values" in reference:
                row["values"] = {item.object_name: item.value for item in result.value}
        elapsed = perf_counter() - start
        if timing:
            row["execution_ms"] = round(elapsed * 1000, 3)
        if "values" in row and "values" in reference:
            checked = compare(reference["values"], row["values"])
            row.update(outcome="match" if checked.passed else "wrong",
                       comparison=checked.to_dict())

    row["as_expected"] = row["outcome"] == candidate["expect"]
    if row["outcome"].endswith("_refusal"):
        row["as_expected"] &= (
            row["outcome"] == f"{expected_refusal.get('stage')}_refusal"
            and expected_refusal["reason"] in row["diagnostic"]
        )
    return row


def run_benchmark(*, timing: bool = False) -> dict:
    benchmark, digest = load_benchmark()
    fixtures = {}
    rows = []
    refusal_questions = {
        case["id"] for case in benchmark["questions"] if "refusal" in case["reference"]
    }
    for case in benchmark["questions"]:
        name = case["fixture"]
        if name not in fixtures:
            fixtures[name] = fixture(name, benchmark["synthetic"])
        inputs, backend = fixtures[name]
        rows.extend(evaluate_candidate(case, candidate, inputs, backend, timing)
                    for candidate in case["candidates"])
    return {
        "benchmark_sha256": digest,
        "summary": {
            "questions": len(benchmark["questions"]),
            "candidates": len(rows),
            "type_admitted": sum(row["type_admitted"] for row in rows),
            "numeric_candidates": sum(row["question"] not in refusal_questions for row in rows),
            "numeric_answers": sum(row["outcome"] in ("match", "wrong") for row in rows),
            "numeric_matches": sum(row["outcome"] == "match" for row in rows),
            "admitted_wrong_answers": sum(row["outcome"] == "wrong" for row in rows),
            "requested_refusals": sum(row["question"] in refusal_questions for row in rows),
            "correct_refusals": sum(row["question"] in refusal_questions and row["as_expected"]
                                    and row["outcome"].endswith("_refusal") for row in rows),
            "expected_outcomes": sum(row["as_expected"] for row in rows),
        },
        "candidates": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Include candidate results and diagnostics.")
    parser.add_argument("--timing", action="store_true", help="Include per-candidate wall-clock time in JSON.")
    args = parser.parse_args()
    if args.timing and not args.json:
        parser.error("--timing requires --json")
    report = run_benchmark(timing=args.timing)
    counts = report["summary"]
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Workflow benchmark: {counts['questions']} questions, {counts['candidates']} candidates")
        print(f"Type admitted: {counts['type_admitted']}/{counts['candidates']}")
        print(f"Numerically correct: {counts['numeric_matches']}/{counts['numeric_answers']} "
              f"returned answers ({counts['numeric_candidates']} candidates)")
        print(f"Type-admitted wrong answers: {counts['admitted_wrong_answers']}")
        print(f"Correct requested refusals: {counts['correct_refusals']}/{counts['requested_refusals']}")
        print(f"Expected outcomes: {counts['expected_outcomes']}/{counts['candidates']}")
        for row in report["candidates"]:
            if not row["as_expected"]:
                print(f"{row['question']} {row['candidate']}: "
                      f"expected {row['expected']}, got {row['outcome']}")
    return int(counts["expected_outcomes"] != counts["candidates"])


if __name__ == "__main__":
    raise SystemExit(main())
