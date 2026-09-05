from redat.core.sections import SECTIONS
from redat.core.sources_meta import SOURCES, for_section


def test_every_section_has_exactly_one_source_row():
    seen = [k for s in SOURCES for k in s.section_keys]
    assert sorted(seen) == sorted(SECTIONS)


def test_rows_are_complete():
    for s in SOURCES:
        assert s.name and s.publisher and s.licence and s.endpoint and s.cadence
        assert s.tier in ("parcel", "area")


def test_for_section():
    assert for_section("noise").publisher.startswith("Land NRW")
    assert for_section("nope") is None
