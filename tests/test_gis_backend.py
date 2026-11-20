import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from examples.amsterdam_noise import DATA, SOURCES, THRESHOLDED, run_example
from executor import ExecutionError, RuntimeDataset, execute
from synthesis import build_chain

HAS_GIS = all(importlib.util.find_spec(package) for package in ("numpy", "rasterio", "shapely"))
if HAS_GIS:
    import numpy as np
    import rasterio
    from rasterio.transform import Affine, from_origin
    from shapely.geometry import MultiPolygon, Polygon, box

    from examples.amsterdam_polygons import run_example as run_polygon_example
    from typed_workflow_layer.gis_backend import PolygonZones, RasterField, RasterPolygonBackend


@unittest.skipUnless(HAS_GIS, "requires the optional GIS dependencies")
class RasterPolygonBackendTest(unittest.TestCase):
    def execute(self, raster, zones, chain=THRESHOLDED):
        return execute(
            build_chain(chain, SOURCES),
            (RuntimeDataset("noise", SOURCES[0].type, raster),
             RuntimeDataset("zone", SOURCES[1].type, zones)),
            backend=RasterPolygonBackend(),
            parameters={"Constrain": {"operator": ">=", "value": 70}},
        ).value

    def test_fractional_cells_and_polygon_hole(self):
        raster = RasterField([[70, 40], [50, 90]], from_origin(0, 2, 1, 1), "EPSG:28992")
        polygon = Polygon(box(0.5, 0, 2, 2).exterior.coords,
                          holes=[box(1.25, 1.25, 1.75, 1.75).exterior.coords])
        zones = PolygonZones((("example", polygon),), "EPSG:28992")
        (area,) = self.execute(raster, zones, THRESHOLDED[:2])
        self.assertAlmostEqual(area.value, 1.5)
        self.assertAlmostEqual(area.denominator, 2.75)
        (share,) = self.execute(raster, zones)
        self.assertAlmostEqual(share.value, 1.5 / 2.75)

    def test_nodata_inside_zone_is_undefined_but_nodata_in_hole_is_allowed(self):
        samples = np.ma.array([[80] * 3] * 3, mask=False)
        samples.mask[1, 1] = True
        raster = RasterField(samples, from_origin(0, 3, 1, 1), "EPSG:28992")
        outer = box(0, 0, 3, 3)
        with self.assertRaisesRegex(ExecutionError, "share is undefined"):
            self.execute(raster, PolygonZones((("whole", outer),), "EPSG:28992"))
        polygon = Polygon(outer.exterior.coords, holes=[box(1, 1, 2, 2).exterior.coords])
        zones = PolygonZones((("hole", polygon),), "EPSG:28992")
        (share,) = self.execute(raster, zones)
        self.assertEqual(share.value, 1.0)

    def test_geotiff_loader_respects_nodata_scale_and_offset(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "example.tif"
            with rasterio.open(path, "w", driver="GTiff", width=2, height=1, count=1,
                               dtype="int16", crs="EPSG:28992", nodata=-9999,
                               transform=from_origin(0, 1, 1, 1)) as target:
                target.write(np.array([[34, -9999]], dtype="int16"), 1)
                target.scales = (2.0,)
                target.offsets = (2.0,)
            raster = RasterField.from_geotiff(path)
        valid = PolygonZones((("valid", box(0, 0, 1, 1)),), "EPSG:28992")
        (share,) = self.execute(raster, valid)
        self.assertEqual(share.value, 1.0)
        with self.assertRaisesRegex(ExecutionError, "share is undefined"):
            invalid = PolygonZones((("whole", box(0, 0, 2, 1)),), "EPSG:28992")
            self.execute(raster, invalid)

    def test_multipolygon_and_extent_errors(self):
        raster = RasterField([[80, 50, 40]], from_origin(0, 1, 1, 1), "EPSG:28992")
        zones = PolygonZones((("multipart", MultiPolygon([box(0, 0, 1, 1), box(2, 0, 3, 1)])),),
                             "EPSG:28992")
        (share,) = self.execute(raster, zones)
        self.assertEqual(share.value, 0.5)
        for geometry in (box(2.5, 0, 3.5, 1), box(-3, -3, -2, -2),
                         box(4, 4, 4.00001, 4.00001)):
            with self.assertRaisesRegex(ExecutionError, "share is undefined"):
                self.execute(raster, PolygonZones((("outside", geometry),), "EPSG:28992"))

    def test_ambiguous_crs_transform_and_geometry_are_refused(self):
        transform = from_origin(0, 2, 1, 1)
        for crs in (None, "EPSG:4326", "EPSG:2263"):
            with self.subTest(crs=crs), self.assertRaisesRegex(ExecutionError, "metre"):
                RasterField([[80]], transform, crs)
        with self.assertRaisesRegex(ExecutionError, "north-up"):
            RasterField([[80]], Affine(1, 0.1, 0, 0, -1, 2), "EPSG:28992")
        raster = RasterField([[80]], transform, "EPSG:28992")
        zones = PolygonZones((("mismatch", box(0, 1, 1, 2)),), "EPSG:32631")
        with self.assertRaisesRegex(ExecutionError, "same projected CRS"):
            self.execute(raster, zones)
        invalid = Polygon([(0, 0), (1, 1), (1, 0), (0, 1)])
        with self.assertRaisesRegex(ExecutionError, "valid polygon"):
            PolygonZones((("invalid", invalid),), "EPSG:28992")

    def test_parity_with_the_offline_rectangle_example(self):
        offline = run_example()["results"]["thresholded"]["shares"]
        grid = json.loads((DATA / "grid.json").read_bytes())
        for zone in grid["zones"]:
            with self.subTest(zone=zone["id"]):
                left, _, _, top = zone["bounds"]
                size = grid["pixel_size_m"]
                raster = RasterField(zone["lden_db"], from_origin(left, top, size, size), grid["crs"])
                zones = PolygonZones(((zone["id"], box(*zone["bounds"])),), grid["crs"])
                (share,) = self.execute(raster, zones)
                self.assertEqual(share.value, offline[zone["id"]])

    def test_real_polygons_against_gdal_fractional_reference(self):
        names, _, _, check = run_polygon_example()
        self.assertEqual(len(names), 3)
        self.assertTrue(check.passed, check.mismatches)
        self.assertLess(check.max_absolute_error, 1e-9)


if __name__ == "__main__":
    unittest.main()
