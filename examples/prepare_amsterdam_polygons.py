"""Freeze three CBS boundaries and crop the pinned RIVM raster to their extent."""

import argparse
import hashlib
import json
from pathlib import Path

import rasterio
from rasterio.features import geometry_window

from examples.prepare_amsterdam_noise import SOURCE


ZONE_CODES = ("BU03633900", "BU03634100", "BU03630106")
CRS_NAME = "urn:ogc:def:crs:EPSG::28992"


def prepare(archive: Path, boundaries: Path, output: Path) -> None:
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != SOURCE["archive_sha256"]:
        raise ValueError("The archive does not match the pinned RIVM snapshot.")

    boundaries = json.loads(boundaries.read_text(encoding="utf-8"))
    if boundaries["crs"]["properties"]["name"] != CRS_NAME:
        raise ValueError("Expected the CBS response in EPSG:28992.")
    by_code = {feature["properties"]["buurtcode"]: feature for feature in boundaries["features"]}
    features = [by_code[code] for code in ZONE_CODES]
    collection = {"type": "FeatureCollection", "crs": boundaries["crs"], "features": features}
    raster_path = f"/vsizip/{archive.resolve().as_posix()}/{SOURCE['raster_member']}"
    with rasterio.open(raster_path) as source:
        if source.crs.to_epsg() != 28992 or source.res != (10, 10):
            raise ValueError("Expected the 10 m RIVM raster in EPSG:28992.")
        window = geometry_window(source, (feature["geometry"] for feature in features))
        values = source.read(1, window=window)
        mask = source.read_masks(1, window=window)
        profile = {
            "driver": "GTiff", "crs": source.crs, "transform": source.window_transform(window),
            "width": values.shape[1], "height": values.shape[0], "count": 1,
            "dtype": values.dtype, "nodata": source.nodata, "compress": "deflate",
        }

    output.mkdir(parents=True, exist_ok=False)
    (output / "zones.geojson").write_text(
        json.dumps(collection, ensure_ascii=False, separators=(",", ":")) + "\n",
        encoding="utf-8", newline="\n",
    )
    with rasterio.Env(GDAL_TIFF_INTERNAL_MASK=True):
        with rasterio.open(output / "noise.tif", "w", **profile) as target:
            target.write(values, 1)
            if not (mask == 255).all():
                target.write_mask(mask)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("boundaries", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.archive, args.boundaries, args.output)
