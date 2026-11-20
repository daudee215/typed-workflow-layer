"""Execute and check two area-share workflows over a frozen RIVM raster extract."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import ccd
from evaluation import compare
from executor import FieldRecord, ObjectRecord, RuntimeDataset, execute
from synthesis import Dataset, build_chain


DATA = Path(__file__).resolve().parent / "data" / "amsterdam_noise"
SOURCES = (
    Dataset("noise", ccd.CCDType(ccd.FIELD, ccd.INTERVAL, ccd.REGION_SUPPORT)),
    Dataset("zone", ccd.CCDType(ccd.OBJECT, ccd.NOMINAL, ccd.REGION_SUPPORT)),
)
THRESHOLDED = (
    ("Constrain", ("noise",)),
    ("Coverage", ("$0", "zone")),
    ("Proportion", ("$1",)),
)
UNFILTERED = (
    ("Coverage", ("noise", "zone")),
    ("Proportion", ("$0",)),
)


def run_example() -> dict:
    """Compare the requested noise share and the type-valid unfiltered share."""
    reference = json.loads((DATA / "reference.json").read_text(encoding="utf-8"))
    raw_grid = (DATA / "grid.json").read_bytes()
    if hashlib.sha256(raw_grid).hexdigest() != reference["grid_sha256"]:
        raise ValueError("The frozen RIVM grid differs from the reference snapshot.")
    grid = json.loads(raw_grid)
    size = grid["pixel_size_m"]
    fields = []
    zones = []
    for zone in grid["zones"]:
        left, bottom, right, top = zone["bounds"]
        zones.append(ObjectRecord(zone["id"], (left, bottom, right, top)))
        for row, values in enumerate(zone["lden_db"]):
            north = top - row * size
            for column, value in enumerate(values):
                west = left + column * size
                fields.append(FieldRecord((west, north - size, west + size, north), value))

    runtime = {
        "noise": RuntimeDataset("noise", SOURCES[0].type, tuple(fields)),
        "zone": RuntimeDataset("zone", SOURCES[1].type, tuple(zones)),
    }
    threshold = reference["threshold_db"]
    intended = build_chain(THRESHOLDED, SOURCES)
    alternative = build_chain(UNFILTERED, SOURCES)
    if intended.result.type != alternative.result.type:
        raise ValueError("The two workflows must produce the same declared output type.")
    executions = {
        "thresholded": execute(
            intended, runtime, parameters={"Constrain": {"operator": ">=", "value": threshold}}
        ),
        "unfiltered": execute(alternative, runtime),
    }
    expected = {zone["id"]: zone["share"] for zone in reference["zones"]}
    results = {}
    for name, execution in executions.items():
        shares = {measure.object_name: measure.value for measure in execution.value}
        results[name] = {
            "shares": shares,
            "comparison": compare(expected, shares).to_dict(),
            "trace": execution.to_dict(),
        }
    return {
        "source": reference["source"],
        "grid_sha256": reference["grid_sha256"],
        "crs": grid["crs"],
        "pixel_size_m": size,
        "threshold_db": threshold,
        "reference": reference["zones"],
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print values and traces as JSON.")
    args = parser.parse_args()
    report = run_example()
    thresholded = report["results"]["thresholded"]
    unfiltered = report["results"]["unfiltered"]
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("RIVM modelled road traffic noise (Lden), 2022")
        print(f"Threshold: >= {report['threshold_db']} dB | "
              f"{report['crs']} | {report['pixel_size_m']} m pixels")
        print()
        print(f"{'Zone':<16} {'Pixels >= threshold':>20} {'Reference':>10} "
              f"{'Executed':>10} {'Unfiltered':>11}")
        for zone in report["reference"]:
            key = zone["id"]
            count = f"{zone['above_threshold_pixels']}/{zone['total_pixels']}"
            print(f"{key:<16} {count:>20} {zone['share']:>10.2%} "
                  f"{thresholded['shares'][key]:>10.2%} {unfiltered['shares'][key]:>11.2%}")
        print()
        print(f"Reference check: {'PASS' if thresholded['comparison']['passed'] else 'FAIL'}")
        print("Unfiltered workflow (type-valid): "
              f"{'PASS' if unfiltered['comparison']['passed'] else 'FAIL against reference'}")
    return int(not thresholded["comparison"]["passed"] or unfiltered["comparison"]["passed"])


if __name__ == "__main__":
    raise SystemExit(main())
