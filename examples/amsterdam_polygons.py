"""Verify fractional raster coverage over three CBS neighbourhoods."""

import hashlib
import json
from pathlib import Path

from shapely.geometry import shape

from evaluation import compare
from examples.amsterdam_noise import SOURCES, THRESHOLDED
from executor import RuntimeDataset, execute
from synthesis import build_chain
from typed_workflow_layer.gis_backend import PolygonZones, RasterField, RasterPolygonBackend


DATA = Path(__file__).resolve().parent / "data" / "amsterdam_polygons"


def run_example():
    reference = json.loads((DATA / "reference.json").read_bytes())
    for filename, key in (("noise.tif", "raster_sha256"), ("zones.geojson", "zones_sha256")):
        if hashlib.sha256((DATA / filename).read_bytes()).hexdigest() != reference[key]:
            raise ValueError(f"{filename} differs from the published snapshot.")
    collection = json.loads((DATA / "zones.geojson").read_bytes())
    names = {
        feature["properties"]["buurtcode"]: feature["properties"]["buurtnaam"]
        for feature in collection["features"]
    }
    zones = PolygonZones(tuple(
        (feature["properties"]["buurtcode"], shape(feature["geometry"]))
        for feature in collection["features"]
    ), collection["crs"]["properties"]["name"])
    raster = RasterField.from_geotiff(DATA / "noise.tif")
    result = execute(
        build_chain(THRESHOLDED, SOURCES),
        (RuntimeDataset("noise", SOURCES[0].type, raster),
         RuntimeDataset("zone", SOURCES[1].type, zones)),
        backend=RasterPolygonBackend(),
        parameters={"Constrain": {"operator": ">=", "value": reference["threshold_db"]}},
    )
    shares = {item.object_name: item.value for item in result.value}
    expected = {zone["code"]: zone["share"] for zone in reference["zones"]}
    check = compare(expected, shares)
    return names, shares, expected, check


def main() -> int:
    names, shares, expected, check = run_example()
    print("Amsterdam neighbourhoods | area at or above 70 dB Lden")
    for code, value in shares.items():
        print(f"{names[code]:<25} {value:>7.2%} (GDAL reference {expected[code]:.2%})")
    print(f"Reference check: {'PASS' if check.passed else 'FAIL'} "
          f"(max absolute share error {check.max_absolute_error:.3g})")
    return int(not check.passed)


if __name__ == "__main__":
    raise SystemExit(main())
