"""Convert the unpacked HWRM shapefiles to the three GeoPackages redat/sources/flood.py prefers.

Input:  <hwrm>/{HQhaeufig,HQ100,HQextrem}-Ueberschwemmungsgrenzen_EPSG25832_Shape/ueberflutungsgrenzen_*.shp
        (the unpacked zips from https://www.opengeodata.nrw.de/produkte/umwelt_klima/wasser/hochwasser/hwrm/,
        dl-de/zero-2-0; the exact file names, including the one with a space, come from flood._SCENARIOS_SHP)
Output: <hwrm>/{HQhaeufig,HQ100,HQextrem}.gpkg - same features, MultiPolygon, R-tree indexed.

flood.py works without this step (it falls back to the shapefiles), but a bbox read against an
un-indexed 300 MB shapefile is slow and the GeoPackages let you delete the unpacked dirs afterwards.
Streams in chunks so peak memory stays a few hundred MB (HQextrem's polygons are huge) - safe under
the compose mem_limit:

    docker compose run --rm --no-deps redat python scripts/build_flood_gpkg.py
    .venv/bin/python scripts/build_flood_gpkg.py --hwrm data/source/flood/hwrm      # local checkout

Idempotent: an existing <HQ>.gpkg is left alone; delete it to rebuild. Normally run via scripts/fetch_geodata.sh.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

import pyogrio

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from redat.sources import flood  # noqa: E402

log = logging.getLogger("build_flood_gpkg")


def build(hwrm: Path, chunk: int = 5_000) -> list[str]:
    """Write <hwrm>/<HQ>.gpkg for every scenario whose shapefile exists and whose gpkg does not. Returns the built ones."""
    root = flood.data_dir()
    built: list[str] = []
    for hq, shp_rel in flood._SCENARIOS_SHP().items():
        shp = hwrm / shp_rel.relative_to(root)
        out = hwrm / f"{hq}.gpkg"
        if out.exists():
            log.info("%s: %s exists, skipping", hq, out.name)
            continue
        if not shp.exists():
            log.warning("%s: shapefile missing at %s, skipping", hq, shp)
            continue
        total = int(pyogrio.read_info(shp)["features"])
        tmp = hwrm / f"{hq}.partial.gpkg"     # must keep the .gpkg extension (GDAL warns otherwise); flood.py never looks for this name
        tmp.unlink(missing_ok=True)
        t0, done = time.time(), 0
        while done < total:
            gdf = pyogrio.read_dataframe(shp, skip_features=done, max_features=chunk)
            if len(gdf) == 0:
                break
            pyogrio.write_dataframe(gdf, tmp, layer=hq, driver="GPKG", append=tmp.exists(), promote_to_multi=True)
            done += len(gdf)
        tmp.rename(out)   # a crash mid-way leaves only the .partial file, never a half-written <HQ>.gpkg
        log.info("%s: %d features -> %s (%.0f MB) in %.0fs", hq, done, out.name, out.stat().st_size / 1e6, time.time() - t0)
        built.append(hq)
    return built


def main(argv: list[str] | None = None) -> int:
    default = Path(os.environ.get("REDAT_DATA_DIR", "data")) / "source" / "flood" / "hwrm"
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--hwrm", type=Path, default=default, help=f"dir with the unpacked zips (default: {default})")
    ap.add_argument("--chunk", type=int, default=5_000)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    built = build(args.hwrm, args.chunk)
    log.info("done: built %s", built or "nothing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
