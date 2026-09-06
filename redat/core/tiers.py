"""Which cards need a house-number-exact location (parcel) and which work on the area."""
from __future__ import annotations

from typing import Optional

SERVICE_TIER: dict[str, str] = {
    "flurstueck": "parcel",
    "boris": "parcel", "boris_trend": "parcel", "irw": "parcel", "flood": "parcel", "starkregen": "parcel", "gfnp": "parcel",
    "planning_essen": "parcel", "planning_bochum": "parcel", "energie": "parcel", "denkmal": "parcel",
    "amenities": "area", "schulen": "area", "unfaelle": "area", "air_quality": "area", "btw": "area", "commute": "area", "noise": "area", "bergbau": "area", "baugrund": "area", "radon": "area",
    "zensus": "area", "schutzgebiete": "area", "breitband": "area", "oepnv": "area", "infrastruktur": "area", "ladesaeulen": "area",
}


def enrichment_allowed(service_tier: str, *, precision: Optional[str], address_verified: bool) -> bool:
    """Parcel-tier sources only run on a verified address or a house-number-level geocode."""
    if service_tier == "area":
        return True
    if address_verified:
        return True
    return precision == "building"
