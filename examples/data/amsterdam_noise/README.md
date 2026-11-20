# Amsterdam road-noise fixture

The question asks what share of each selected 300 m square falls in a modelled
road-noise class of at least 70 dB Lden. RIVM reports the surface in 1 dB classes
at 10 m resolution. The three windows were selected to illustrate differing
coverage levels. They are analysis windows with fixed coordinates. The results
apply to those windows and the modelled road-noise surface.

## Source

Attribution to **RIVM / Atlas Leefomgeving (ALO)**. The source is the 2022
edition of [Geluid van wegverkeer (Lden)](https://data.rivm.nl/meta/srv/api/records/f9a57393-176a-4eaf-9ce8-276f7a531a92).
The [publisher's map notes](https://www.atlasleefomgeving.nl/geluid-in-nederland-van-wegverkeer-lden)
describe the model year, road data and limits. The catalogue marks the data
with the [Public Domain Mark 1.0](https://creativecommons.org/publicdomain/mark/1.0/).

The [source ZIP](https://data.rivm.nl/data/alo/rivm_20250101_Geluid_lden_wegverkeer_2022.zip)
and TIFF member are identified in [reference.json](reference.json). The
preparation script checks the ZIP's SHA-256 before reading it. The example
checks the SHA-256 of the resulting [grid extract](grid.json).

## Method

The grid uses RD New (`EPSG:28992`). Bounds below are ordered west, south,
east, north in metres. Each window is aligned with the source grid and
contains 900 valid 10 m cells. Values are stored from north to south and from
west to east within each row. The extraction preserves the raster's class
values and coordinates.

| Window | Bounds in EPSG:28992 |
| --- | --- |
| West | 117900, 487700, 118200, 488000 |
| Central | 121000, 487000, 121300, 487300 |
| South | 119900, 483500, 120200, 483800 |

The reference is the direct count of cells whose stored class is at least 70,
divided by 900. Equal cell area and aligned boundaries make this the area share.
The preparation code calculates the counts directly from the raster array,
independently of workflow execution and its rectangle overlay.

## Regenerate the extract

Download the linked ZIP and install Rasterio in a separate environment.
Run these commands from the repository root with that environment active.

```bash
python -m pip install rasterio==1.5.2
python -m examples.prepare_amsterdam_noise /path/to/rivm_20250101_Geluid_lden_wegverkeer_2022.zip --output reproduced-amsterdam-noise
```

Compare the generated `grid.json` and `reference.json` with the files here.
Rasterio is used only to regenerate the fixture. Run the committed example with
`python -m examples.amsterdam_noise`.
