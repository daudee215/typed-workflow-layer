"""Rebuild the Amsterdam fixture and its independent raster-count reference."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


SOURCE = {
    "provider": "RIVM / Atlas Leefomgeving",
    "title": "Geluid van wegverkeer (Lden)",
    "model_year": 2022,
    "catalogue_url": "https://data.rivm.nl/meta/srv/api/records/f9a57393-176a-4eaf-9ce8-276f7a531a92",
    "archive_url": "https://data.rivm.nl/data/alo/rivm_20250101_Geluid_lden_wegverkeer_2022.zip",
    "archive_sha256": "08970ba561c90ac93de8408b09328af2ace6198e113bbb2ab39f89ba4e157f69",
    "raster_member": "rivm_20250101_Geluid_lden_wegverkeer_2022.tif",
    "rights_url": "https://creativecommons.org/publicdomain/mark/1.0/",
}
ZONES = {
    "west": (117900, 487700, 118200, 488000),
    "central": (121000, 487000, 121300, 487300),
    "south": (119900, 483500, 120200, 483800),
}
THRESHOLD_DB = 70


def json_bytes(value: dict) -> bytes:
    return (json.dumps(value, indent=2) + "\n").encode("utf-8")


def prepare(archive: Path, output: Path) -> None:
    import rasterio
    from rasterio.windows import from_bounds

    archive = archive.resolve()
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != SOURCE["archive_sha256"]:
        raise ValueError("The archive does not match the pinned RIVM snapshot.")

    grid = {"crs": "EPSG:28992", "pixel_size_m": 10, "zones": []}
    rows = []
    raster_path = f"/vsizip/{archive.as_posix()}/{SOURCE['raster_member']}"
    with rasterio.open(raster_path) as raster:
        if (raster.crs.to_epsg() != 28992 or raster.res != (10.0, 10.0)
                or not raster.transform.is_rectilinear):
            raise ValueError("Expected a 10 m raster aligned to EPSG:28992.")
        for name, bounds in ZONES.items():
            window = from_bounds(*bounds, raster.transform)
            if raster.window_bounds(window) != bounds:
                raise ValueError(f"Zone {name} is not aligned with the source raster.")
            pixels = raster.read(1, window=window, masked=True)
            if pixels.shape != (30, 30) or pixels.count() != pixels.size:
                raise ValueError(f"Expected 900 valid pixels in zone {name}.")
            grid["zones"].append({"id": name, "bounds": bounds, "lden_db": pixels.tolist()})

            # Count raster cells directly, without any rectangle overlay or workflow code.
            covered = int((pixels >= THRESHOLD_DB).sum())
            rows.append({
                "id": name,
                "total_pixels": int(pixels.size),
                "above_threshold_pixels": covered,
                "share": covered / pixels.size,
            })

    grid_data = json_bytes(grid)
    reference = {
        "source": SOURCE,
        "grid_sha256": hashlib.sha256(grid_data).hexdigest(),
        "threshold_db": THRESHOLD_DB,
        "zones": rows,
    }
    output.mkdir(parents=True, exist_ok=False)
    (output / "grid.json").write_bytes(grid_data)
    (output / "reference.json").write_bytes(json_bytes(reference))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="Pinned RIVM ZIP archive.")
    parser.add_argument("--output", type=Path, required=True, help="New output directory.")
    args = parser.parse_args()
    prepare(args.archive, args.output)


if __name__ == "__main__":
    main()
