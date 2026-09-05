#!/usr/bin/env bash
# Fetch every non-git geodata asset REDAT needs and build the derived GeoPackages. New-server runbook:
#
#   git clone <repo> nrw-redat && cd nrw-redat && cp .env.example .env   # fill in GEOAPIFY_API_KEY
#   docker compose build                                                # the build steps below run inside this image
#   scripts/fetch_geodata.sh                                            # ~3.3 GB download, ~10 min total
#   docker compose up -d
#
# Everything is public open data (dl-de/zero-2-0, no login). Idempotent: whatever already exists is
# skipped, so re-running after an interrupted download is safe. Layout it produces under $DATA_DIR/source:
#
#   boris/BRW_{2011..2025}/BRW_{year}_Polygon.shp   BORIS Bodenrichtwert zones per Stichtag (15 x ~200 MB)
#   boris/brw.gpkg                                   derived: one R-tree layer per year (scripts/build_boris_gpkg.py)
#   flood/hwrm/<zip name>/ueberflutungsgrenzen_*.shp HWRM Ueberschwemmungsgrenzen HQhaeufig / HQ100 / HQextrem
#   flood/hwrm/{HQhaeufig,HQ100,HQextrem}.gpkg       derived (scripts/build_flood_gpkg.py)
#   elections/btw25/wahlkreise_shp_geo/*.shp         Bundestagswahl 2025 Wahlkreis geometry (5 MB)
#
# Options:
#   --data-dir DIR   host data dir (default ./data = the compose bind mount for /data)
#   --only NAME      boris | flood | btw  (repeatable); default: all three
#   --no-build       download/unpack only, skip the GeoPackage builds
#   --prune          after a successful build, delete the unpacked shapefile dirs the .gpkg files replace
#                    (frees ~6.6 GB; boris.py/flood.py fall back to shapefiles only for years/scenarios
#                    missing from the .gpkg, so keep them if you want that safety net)
#   --python CMD     how to run the build scripts (default: `docker compose run --rm --no-deps -T --user … redat python`
#                    if docker compose is available, else `python3`). With docker, --data-dir must stay ./data.
set -euo pipefail

BASE_BORIS=https://www.opengeodata.nrw.de/produkte/infrastruktur_bauen_wohnen/boris/BRW
BASE_HWRM=https://www.opengeodata.nrw.de/produkte/umwelt_klima/wasser/hochwasser/hwrm
URL_BTW25=https://www.bundeswahlleiterin.de/dam/jcr/a3b60aa9-8fa5-4223-9fb4-0a3a3cebd7d1/btw25_geometrie_wahlkreise_vg250_shp_geo.zip
YEARS=$(seq 2011 2025)
HQS="HQhaeufig HQ100 HQextrem"

REPO=$(cd "$(dirname "$0")/.." && pwd)
DATA_DIR="$REPO/data"; ONLY=(); BUILD=1; PRUNE=0; PY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --data-dir) DATA_DIR=$(cd "$(dirname "$2")" && pwd)/$(basename "$2"); shift 2 ;;
    --only) ONLY+=("$2"); shift 2 ;;
    --no-build) BUILD=0; shift ;;
    --prune) PRUNE=1; shift ;;
    --python) PY="$2"; shift 2 ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
[ ${#ONLY[@]} -eq 0 ] && ONLY=(boris flood btw)
want() { printf '%s\n' "${ONLY[@]}" | grep -qx "$1"; }
log() { echo "[$(date +%H:%M:%S)] $*"; }
for tool in curl unzip; do command -v "$tool" >/dev/null || { echo "$tool is required" >&2; exit 1; }; done

if [ $BUILD -eq 1 ] && [ -z "$PY" ]; then
  if command -v docker >/dev/null && docker compose version >/dev/null 2>&1 && [ -f "$REPO/docker-compose.yml" ]; then
    # as the invoking user, so brw.gpkg & co. are not root-owned in ./data (the app itself runs as root)
    PY="docker compose run --rm --no-deps -T --user $(id -u):$(id -g) -e HOME=/tmp redat python"
    [ "$DATA_DIR" = "$REPO/data" ] || { echo "--data-dir other than ./data needs --python (the container only sees ./data as /data)" >&2; exit 2; }
    docker image inspect nrw-redat:latest >/dev/null 2>&1 || { echo "image nrw-redat:latest not built yet - run 'docker compose build' first (or pass --python)" >&2; exit 1; }
  else
    PY="python3"
  fi
fi

SRC="$DATA_DIR/source"
mkdir -p "$SRC"
# The container runs as root and creates root-owned files under ./data; make sure we can write here.
[ -w "$SRC" ] || { echo "$SRC is not writable by $(id -un) - e.g. sudo chown -R $(id -u):$(id -g) $DATA_DIR" >&2; exit 1; }

fetch_unzip() {  # url, zipfile, target dir -> downloads (resumable) and unpacks, then removes the zip
  local url=$1 zip=$2 dest=$3
  log "download $(basename "$url")"
  curl -fsSL --retry 5 --retry-all-errors -C - -o "$zip" "$url"
  mkdir -p "$dest" && unzip -q -o "$zip" -d "$dest" && rm -f "$zip"
}

# ------------------------------------------------------------------ 1. BORIS 2011-2025
if want boris; then
  mkdir -p "$SRC/boris"
  for y in $YEARS; do
    if ls "$SRC/boris/BRW_$y/"*.shp >/dev/null 2>&1; then log "boris $y present"; continue; fi
    fetch_unzip "$BASE_BORIS/BRW_${y}_EPSG25832_Shape.zip" "$SRC/boris/BRW_${y}.zip" "$SRC/boris/BRW_$y"
  done
fi

# ------------------------------------------------------------------ 2. HWRM flood zones
if want flood; then
  mkdir -p "$SRC/flood/hwrm"
  for hq in $HQS; do
    name="${hq}-Ueberschwemmungsgrenzen_EPSG25832_Shape"
    if [ -f "$SRC/flood/hwrm/$hq.gpkg" ] || ls "$SRC/flood/hwrm/$name/"*.shp >/dev/null 2>&1; then log "flood $hq present"; continue; fi
    fetch_unzip "$BASE_HWRM/$name.zip" "$SRC/flood/hwrm/$name.zip" "$SRC/flood/hwrm/$name"
  done
fi

# ------------------------------------------------------------------ 3. BTW25 Wahlkreise
if want btw; then
  if ls "$SRC/elections/btw25/wahlkreise_shp_geo/"*.shp >/dev/null 2>&1; then log "btw25 present"
  else
    mkdir -p "$SRC/elections/btw25"
    fetch_unzip "$URL_BTW25" "$SRC/elections/btw25/btw25.zip" "$SRC/elections/btw25/wahlkreise_shp_geo"
  fi
fi

# ------------------------------------------------------------------ 4. derived GeoPackages
if [ $BUILD -eq 1 ]; then
  want boris && { log "build boris/brw.gpkg ($PY)"; $PY scripts/build_boris_gpkg.py; }
  want flood && { log "build flood/hwrm/{HQ}.gpkg"; $PY scripts/build_flood_gpkg.py; }
  if [ $PRUNE -eq 1 ]; then
    # Reaching this line means both build scripts exited 0 (set -e), i.e. every year/scenario that has a
    # shapefile now has its layer/.gpkg - so the unpacked shapefiles are redundant.
    if want boris && [ -f "$SRC/boris/brw.gpkg" ]; then
      for y in $YEARS; do [ -d "$SRC/boris/BRW_$y" ] && rm -rf "$SRC/boris/BRW_$y" && log "pruned boris/BRW_$y"; done
    fi
    if want flood; then
      for hq in $HQS; do
        [ -f "$SRC/flood/hwrm/$hq.gpkg" ] && rm -rf "$SRC/flood/hwrm/${hq}-Ueberschwemmungsgrenzen_EPSG25832_Shape" && log "pruned flood/hwrm/$hq shapefiles"
      done
    fi
  fi
fi

log "done. $(du -sh "$SRC" 2>/dev/null | cut -f1) under $SRC"
[ $BUILD -eq 1 ] && echo "If the app is already running: docker compose restart redat  (in-process lookups cache 'no data' answers)"
exit 0
