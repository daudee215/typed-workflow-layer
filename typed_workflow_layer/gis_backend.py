"""Optional fractional raster coverage in a shared projected metre CRS."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Mapping, Sequence

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.errors import CRSError
from rasterio.transform import Affine
from rasterio.windows import from_bounds
import shapely
from shapely.geometry import MultiPolygon, Polygon

from executor import Backend, ExecutionError, ObjectMeasure, RectangularBackend, _comparison, _number


def _projected_crs(value: CRS | str | None) -> CRS:
    try:
        crs = CRS.from_user_input(value)
    except (CRSError, TypeError, ValueError) as error:
        raise ExecutionError("a projected CRS with metre units is required") from error
    if not crs.is_projected or crs.linear_units_factor[1] != 1.0:
        raise ExecutionError("a projected CRS with metre units is required")
    return crs


@dataclass(frozen=True)
class RasterField:
    """A north-up raster with finite values, explicit georeferencing and a valid-cell mask."""

    values: np.ndarray
    transform: Affine
    crs: CRS | str
    valid: np.ndarray = field(init=False, repr=False)

    def __post_init__(self) -> None:
        transform = self.transform
        if (not isinstance(transform, Affine)
                or not all(math.isfinite(value) for value in transform[:6])
                or transform.a <= 0 or transform.e >= 0
                or transform.b != 0 or transform.d != 0):
            raise ExecutionError("a finite, unrotated north-up raster transform is required")
        samples = np.ma.asarray(self.values)
        if samples.ndim != 2 or not samples.size or samples.dtype.kind not in "biuf":
            raise ExecutionError("raster values must be a non-empty two-dimensional numeric array")
        values = np.array(samples.data, copy=True)
        valid = np.isfinite(values) & ~np.ma.getmaskarray(samples)
        values.setflags(write=False)
        valid.setflags(write=False)
        object.__setattr__(self, "values", values)
        object.__setattr__(self, "valid", valid)
        object.__setattr__(self, "crs", _projected_crs(self.crs))

    @classmethod
    def from_geotiff(cls, path, *, band: int = 1) -> RasterField:
        """Load a bounded raster band, keeping its mask, scale and offset."""
        with rasterio.open(path) as source:
            values = source.read(band, masked=True)
            scale, offset = source.scales[band - 1], source.offsets[band - 1]
            if not math.isfinite(scale) or not math.isfinite(offset):
                raise ExecutionError("raster scale and offset must be finite")
            if (scale, offset) != (1.0, 0.0):
                values = values.astype("float64") * scale + offset
            return cls(values, source.transform, source.crs)


@dataclass(frozen=True)
class PolygonZones:
    """Named valid polygons or multipolygons in an explicitly declared CRS."""

    zones: tuple[tuple[str, Polygon | MultiPolygon], ...]
    crs: CRS | str

    def __post_init__(self) -> None:
        zones = tuple(self.zones)
        if not zones:
            raise ExecutionError("at least one polygon zone is required")
        names = set()
        for name, geometry in zones:
            if not isinstance(name, str) or not name.strip() or name in names:
                raise ExecutionError("polygon zones need unique, non-empty names")
            if (not isinstance(geometry, (Polygon, MultiPolygon))
                    or not geometry.is_valid or not math.isfinite(geometry.area)
                    or geometry.area <= 0):
                raise ExecutionError(f"zone {name!r} must be a valid polygon with positive area")
            names.add(name)
        object.__setattr__(self, "zones", zones)
        object.__setattr__(self, "crs", _projected_crs(self.crs))


@dataclass(frozen=True)
class _Selection:
    raster: RasterField
    cells: np.ndarray


class RasterPolygonBackend(Backend):
    """Execute Constrain, Coverage and Proportion over a bounded georeferenced raster."""

    def run(self, transformation: str, inputs: Sequence[Any],
            parameters: Mapping[str, Any]) -> Any:
        if transformation == "Proportion":
            return RectangularBackend().run(transformation, inputs, parameters)
        if transformation == "Constrain":
            if len(inputs) != 1:
                raise ExecutionError("Constrain expects one raster")
            selection = self._selection(inputs[0])
            try:
                comparison = _comparison(str(parameters["operator"]))
                threshold = _number(parameters["value"], "constraint value")
            except KeyError as error:
                raise ExecutionError("Constrain requires 'operator' and 'value'") from error
            cells = selection.cells & comparison(selection.raster.values, threshold)
            return _Selection(selection.raster, cells)
        if transformation == "Coverage":
            if len(inputs) != 2 or not isinstance(inputs[1], PolygonZones):
                raise ExecutionError("Coverage expects a raster and polygon zones")
            selection = self._selection(inputs[0])
            zones = inputs[1]
            if selection.raster.crs != zones.crs:
                raise ExecutionError("raster and zones must use the same projected CRS")
            return tuple(self._measure(selection, name, zone) for name, zone in zones.zones)
        raise ExecutionError(f"the raster-polygon backend does not implement {transformation}")

    @staticmethod
    def _selection(value: RasterField | _Selection) -> _Selection:
        if isinstance(value, _Selection):
            return value
        if isinstance(value, RasterField):
            return _Selection(value, value.valid)
        raise ExecutionError("expected a RasterField")

    @staticmethod
    def _measure(selection: _Selection, name: str, zone: Polygon | MultiPolygon) -> ObjectMeasure:
        raster = selection.raster
        window = from_bounds(*zone.bounds, transform=raster.transform)
        row_start = max(0, math.floor(window.row_off))
        col_start = max(0, math.floor(window.col_off))
        row_stop = max(row_start, min(raster.values.shape[0], math.ceil(window.row_off + window.height)))
        col_stop = max(col_start, min(raster.values.shape[1], math.ceil(window.col_off + window.width)))
        rows, columns = np.nonzero(raster.valid[row_start:row_stop, col_start:col_stop])
        rows += row_start
        columns += col_start
        grid = raster.transform
        west = grid.c + columns * grid.a
        north = grid.f + rows * grid.e
        cells = shapely.box(west, north + grid.e, west + grid.a, north)
        areas = shapely.area(shapely.intersection(cells, zone))

        total_area = zone.area
        valid_area = float(areas.sum())
        if not math.isclose(valid_area, total_area, rel_tol=1e-9):
            raise ExecutionError(
                f"zone {name!r} has {valid_area:.6g} of {total_area:.6g} m² "
                "covered by valid raster cells; whole-zone share is undefined"
            )
        covered_area = float(areas[selection.cells[rows, columns]].sum())
        return ObjectMeasure(name, min(covered_area, total_area), total_area)
