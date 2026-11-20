# Amsterdam neighbourhood polygons

The example asks what share of each CBS neighbourhood was mapped in a road-noise
class of 70 dB Lden or higher. It uses a 10 m crop of RIVM's 2022 road-noise
raster and three 2022 neighbourhood boundaries in RD New (`EPSG:28992`).

## Sources and snapshot

- Raster source **RIVM / Atlas Leefomgeving (ALO)**. The [RIVM source guide](../amsterdam_noise/README.md#source)
  identifies the national ZIP, its terms and pinned checksum. The crop preserves
  the source values, pixel grid and CRS.
- Boundary source **CBS and Kadaster**, [Wijk- en buurtkaart 2022](https://www.cbs.nl/nl-nl/dossier/nederland-regionaal/geografische-data/wijk-en-buurtkaart),
  obtained through the [PDOK WFS](https://www.pdok.nl/ogc-webservices/-/article/cbs-wijken-en-buurten).
  The public 2022 dataset is listed under [CC BY 4.0](https://data.overheid.nl/dataset/81629-wijk--en-buurtkaart-2022-versie-3).
  The fixture retains the three source geometries and original neighbourhood codes
  and names. The GeoJSON contains the service's explicit projected CRS declaration.
- [reference.json](reference.json) records the byte checksums for the crop and
  the boundaries, the threshold, and the independent zonal statistics.

To regenerate the crop, use the [pinned RIVM ZIP](../amsterdam_noise/README.md#regenerate-the-extract)
and the committed `zones.geojson` as inputs:

```bash
python -m examples.prepare_amsterdam_polygons /path/to/rivm_20250101_Geluid_lden_wegverkeer_2022.zip examples/data/amsterdam_polygons/zones.geojson --output reproduced-amsterdam-polygons
```

The command requires the GIS extra. The extractor writes the input geometries
and a compressed GeoTIFF in a new directory. TIFF encoding may differ across
GDAL builds. Compare pixel values, masks, transform and CRS when rebuilding
with another version.

## Independent reference

The reference uses GDAL 3.13.2 with fractional zonal statistics. Reclassify the
16-bit source crop into a binary raster, then use fractional pixel weights:

```bash
gdal raster reclassify noise.tif binary-noise.tif --mapping "[-32768,70)=0; [70,32767]=1" --ot UInt8
gdal raster zonal-stats binary-noise.tif check.geojson --zones zones.geojson --include-field buurtcode --pixels fractional --stat count --stat sum --stat mean
```

The fractionally weighted sum counts qualifying pixels, the fractional count
gives the total valid cell equivalents, and the binary mean gives their ratio.
These three polygons have full valid coverage. The optional backend compares
the whole polygon area with valid cell intersections and raises an error if
they differ beyond floating-point tolerance. This prevents nodata, missing
raster extent or a zero denominator from silently changing the question.
