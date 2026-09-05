import pytest

from redat.core.tiers import SERVICE_TIER, enrichment_allowed


def test_every_section_has_a_tier():
    for key in ("flurstueck", "boris", "boris_trend", "irw", "flood", "starkregen", "noise", "bergbau", "baugrund", "radon", "gfnp", "schutzgebiete", "planning_essen",
                "planning_bochum", "denkmal", "amenities", "schulen", "unfaelle", "oepnv", "zensus", "energie", "breitband", "infrastruktur",
                "air_quality", "btw", "commute"):
        assert SERVICE_TIER[key] in ("parcel", "area")


def test_parcel_tier_keys():
    assert {k for k, t in SERVICE_TIER.items() if t == "parcel"} == {
        "flurstueck", "boris", "boris_trend", "irw", "flood", "starkregen", "gfnp", "planning_essen", "planning_bochum", "energie", "denkmal"}


@pytest.mark.parametrize("precision,verified,expected", [
    ("building", False, True), ("street", False, False), (None, False, False),
    ("street", True, True), (None, True, True), ("coordinates", False, False),
])
def test_parcel_gate(precision, verified, expected):
    assert enrichment_allowed("parcel", precision=precision, address_verified=verified) is expected


def test_area_always_allowed():
    assert enrichment_allowed("area", precision=None, address_verified=False) is True
