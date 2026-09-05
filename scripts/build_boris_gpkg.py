"""Build <boris dir>/brw.gpkg - one R-tree-indexed layer per BRW year - from the yearly NRW shapefiles.

Why: redat/sources/boris.py answers a point query with one bbox-limited read. Against a bare shapefile
GDAL has no spatial index and scans the whole 200-400 MB file (~2 s cold, times 15 years for the
boris_trend card); against a GeoPackage layer the R-tree makes the same read a few milliseconds.
Attributes are carried over 1:1, and boris.py falls back to BRW_{year}/BRW_{year}_Polygon.shp for any
year missing from the .gpkg, so the shapefiles keep working with or without this step.

Input:  <src>/BRW_{year}/BRW_{year}_Polygon.shp - the unpacked BRW_{year}_EPSG25832_Shape.zip files
        from https://www.opengeodata.nrw.de/produkte/infrastruktur_bauen_wohnen/boris/BRW/ (dl-de/zero-2-0)
Output: <src>/brw.gpkg with layers brw_2011 ... brw_2025, geometry promoted to MultiPolygon. Roughly the
        size of the shapefiles; they can be deleted once the layers exist.

The shapefiles are streamed in chunks (default 10 000 features) so peak memory stays a few hundred MB
whatever the file size - a full read of one year is ~1 GB - which keeps it safe under the compose
mem_limit:

    docker compose run --rm --no-deps redat python scripts/build_boris_gpkg.py
    .venv/bin/python scripts/build_boris_gpkg.py --src data/source/boris        # local checkout

Idempotent: a year whose layer already holds as many features as its shapefile is skipped; a layer
left half-written by an interrupted run is wiped and rebuilt. Delete the file to rebuild everything.

Encoding: the 2022-2024 NRW files declare UTF-8 in .cpg but contain a few hundred ISO-8859-1 rows
(Gutachterausschuss Moers). A chunk that fails to decode is re-read as Latin-1 and repaired per value
(`redat.sources.boris.repair_mixed_encoding`), so the GeoPackage ends up clean UTF-8 throughout.
"""
from __future__ import annotations

import argparse
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path

import pyogrio

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # `python scripts/x.py` puts scripts/ on sys.path, not the repo root
from redat.sources.boris import repair_mixed_encoding  # noqa: E402

DEFAULT_YEARS = list(range(2011, 2026))
GPKG_NAME = "brw.gpkg"
log = logging.getLogger("build_boris_gpkg")


def _shapefile(src: Path, year: int) -> Path | None:
    exact = src / f"BRW_{year}" / f"BRW_{year}_Polygon.shp"
    if exact.exists():
        return exact
    year_dir = src / f"BRW_{year}"
    hits = sorted(year_dir.glob("*.shp")) if year_dir.exists() else []
    return hits[0] if hits else None


def _existing_layers(out: Path) -> set[str]:
    return {name for name, _geom in pyogrio.list_layers(out).tolist()} if out.exists() else set()


def _read_chunk(shp: Path, skip: int, n: int):
    try:
        return pyogrio.read_dataframe(shp, skip_features=skip, max_features=n)
    except UnicodeDecodeError:
        log.warning("%s: features %d-%d contain non-UTF-8 rows, re-reading as ISO-8859-1 with per-value repair", shp.name, skip, skip + n)
        return repair_mixed_encoding(pyogrio.read_dataframe(shp, skip_features=skip, max_features=n, encoding="ISO-8859-1"))


def _wipe_layer(out: Path, layer: str) -> None:
    """Empty a half-written layer in place; the GPKG R-tree/feature-count triggers keep the metadata consistent."""
    with sqlite3.connect(out) as con:
        con.execute(f'DELETE FROM "{layer}"')


def build(src: Path, out: Path, years: list[int] = DEFAULT_YEARS, chunk: int = 10_000) -> list[int]:
    """Append one `brw_{year}` layer per year that has a shapefile. Returns the years actually built."""
    out.parent.mkdir(parents=True, exist_ok=True)
    have = _existing_layers(out)
    built: list[int] = []
    for year in years:
        layer = f"brw_{year}"
        shp = _shapefile(src, year)
        if shp is None:
            log.warning("%s: no shapefile under %s, skipping", layer, src / f"BRW_{year}")
            continue
        total = int(pyogrio.read_info(shp)["features"])
        if layer in have:
            got = int(pyogrio.read_info(out, layer=layer)["features"])
            if got == total:
                log.info("%s: layer complete (%d features), skipping", layer, total)
                continue
            log.warning("%s: layer holds %d of %d features (interrupted run?), rebuilding", layer, got, total)
            _wipe_layer(out, layer)
        t0, done = time.time(), 0
        while done < total:
            gdf = _read_chunk(shp, done, chunk)
            if len(gdf) == 0:
                break
            # append=True onto an existing file adds a new layer or extends the current one; the very
            # first write has to create the file.
            pyogrio.write_dataframe(gdf, out, layer=layer, driver="GPKG", append=out.exists(), promote_to_multi=True)
            done += len(gdf)
        log.info("%s: %d features from %s in %.0fs", layer, done, shp.name, time.time() - t0)
        built.append(year)
    return built


def _parse_years(spec: str) -> list[int]:
    if "-" in spec:
        a, b = spec.split("-", 1)
        return list(range(int(a), int(b) + 1))
    return [int(y) for y in spec.split(",") if y]


def main(argv: list[str] | None = None) -> int:
    default_src = Path(os.environ.get("REDAT_DATA_DIR", "data")) / "source" / "boris"
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--src", type=Path, default=default_src, help=f"dir holding BRW_{{year}}/ (default: {default_src})")
    ap.add_argument("--out", type=Path, default=None, help=f"output GeoPackage (default: <src>/{GPKG_NAME})")
    ap.add_argument("--years", default="2011-2025", help="e.g. 2011-2025 or 2024,2025")
    ap.add_argument("--chunk", type=int, default=10_000, help="features per read/write batch")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    out = args.out or args.src / GPKG_NAME
    built = build(args.src, out, _parse_years(args.years), args.chunk)
    log.info("done: built %s -> %s (%.1f GB)", built or "nothing", out, out.stat().st_size / 1e9 if out.exists() else 0)
    return 0


if __name__ == "__main__":
    sys.exit(main())
