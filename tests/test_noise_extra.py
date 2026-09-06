from redat.sources import noise_extra as ne


def stub(monkeypatch, by_url: dict):
    calls = []

    def fake(url, lat, lon, out_fields):
        calls.append(url)
        v = by_url.get(url, [])
        if isinstance(v, Exception):
            raise v
        return {"features": [{"attributes": a} for a in v]}
    monkeypatch.setattr(ne, "_query", fake)
    return calls


def test_essen_kettwig_flug_dus_wins_over_emh(monkeypatch):
    # DUS day+night and EMH day all have features; DUS wins (EMH is queried but ignored in the merge).
    calls = stub(monkeypatch, {
        ne.ESSEN_FLUG_DUS_DAY: [{"CATEGORY": "Lden5559", "PEGEL": "LDEN", "TEXT": "ab 55 bis 59 dB(A)"}],
        ne.ESSEN_FLUG_DUS_NIGHT: [{"CATEGORY": "Lnight5054", "PEGEL": "LNIGHT", "TEXT": "ab 50 bis 54 dB(A)"}],
        ne.ESSEN_FLUG_EMH_DAY: [{"TEXT": "ab 60 bis 64 dB(A)"}],
    })
    d = ne.get_noise_extra(51.362, 6.940)
    assert d["flug"] == {"airport": "DUS", "day": "ab 55 bis 59 dB(A)", "night": "ab 50 bis 54 dB(A)"}
    assert d["ruhiges_gebiet"] is None
    called = set(calls)
    assert called == {ne.ESSEN_FLUG_DUS_DAY, ne.ESSEN_FLUG_DUS_NIGHT, ne.ESSEN_FLUG_EMH_DAY, ne.ESSEN_RUHIG}
    assert ne.BOCHUM_RUHIG not in called


def test_essen_emh_when_dus_has_no_feature(monkeypatch):
    calls = stub(monkeypatch, {ne.ESSEN_FLUG_EMH_DAY: [{"TEXT": "ab 55 bis 59 dB(A)"}]})
    d = ne.get_noise_extra(51.40, 6.95)
    assert d["flug"] == {"airport": "EMH", "day": "ab 55 bis 59 dB(A)", "night": None}
    assert set(calls) == {ne.ESSEN_FLUG_DUS_DAY, ne.ESSEN_FLUG_DUS_NIGHT, ne.ESSEN_FLUG_EMH_DAY, ne.ESSEN_RUHIG}


def test_dus_day_error_does_not_fall_back_to_emh(monkeypatch):
    # DUS-day *erroring* (not "no feature") must not be reported as "kein Fluglärm" via EMH.
    calls = stub(monkeypatch, {ne.ESSEN_FLUG_DUS_DAY: RuntimeError("down"), ne.ESSEN_FLUG_EMH_DAY: [{"TEXT": "ab 55 bis 59 dB(A)"}]})
    d = ne.get_noise_extra(51.362, 6.940)
    assert d["flug"] is None
    assert d["errors"] == {"flug_dus_day": "down"}
    assert ne.ESSEN_FLUG_EMH_DAY in calls  # still queried, just ignored in the merge


def test_ruhiges_gebiet_essen_only(monkeypatch):
    stub(monkeypatch, {ne.ESSEN_RUHIG: [{"NAME": "Stadtwald", "BESCHREIBU": "Stadtwald"}]})
    d = ne.get_noise_extra(51.42, 7.02)
    assert d["ruhiges_gebiet"] == {"name": "Stadtwald", "stadt": "Essen"}


def test_ruhiges_gebiet_bochum_only(monkeypatch):
    calls = stub(monkeypatch, {ne.BOCHUM_RUHIG: [{"NAME": "Weitmarer Holz", "ART": "Ruhiges Gebiet", "BEZIRK": "Südwest"}]})
    d = ne.get_noise_extra(51.4818, 7.2162)
    assert d["ruhiges_gebiet"] == {"name": "Weitmarer Holz", "stadt": "Bochum"} and d["flug"] is None
    assert ne.ESSEN_FLUG_DUS_DAY not in calls and ne.ESSEN_RUHIG not in calls


def test_overlap_band_queries_both_cities_ruhig_layers(monkeypatch):
    # Bochum-Wattenscheid (~51.467/7.129) sits in both ESSEN_BBOX and BOCHUM_BBOX: only Bochum's
    # layer has a feature, and it must still be reached even though Essen is checked first.
    calls = stub(monkeypatch, {ne.BOCHUM_RUHIG: [{"NAME": "Halde Prosper", "ART": "Ruhiges Gebiet", "BEZIRK": "Wattenscheid"}]})
    d = ne.get_noise_extra(51.467, 7.129)
    assert d["ruhiges_gebiet"] == {"name": "Halde Prosper", "stadt": "Bochum"}
    assert set(calls) == {ne.ESSEN_FLUG_DUS_DAY, ne.ESSEN_FLUG_DUS_NIGHT, ne.ESSEN_FLUG_EMH_DAY, ne.ESSEN_RUHIG, ne.BOCHUM_RUHIG}


def test_overlap_band_essen_wins_when_both_ruhig_layers_hit(monkeypatch):
    stub(monkeypatch, {ne.ESSEN_RUHIG: [{"NAME": "Stadtwald"}], ne.BOCHUM_RUHIG: [{"NAME": "Halde Prosper"}]})
    d = ne.get_noise_extra(51.467, 7.129)
    assert d["ruhiges_gebiet"] == {"name": "Stadtwald", "stadt": "Essen"}


def test_outside_both_cities_queries_nothing(monkeypatch):
    calls = stub(monkeypatch, {})
    assert ne.get_noise_extra(51.2199, 6.7943) == {"flug": None, "ruhiges_gebiet": None, "errors": {}} and calls == []


def test_one_layer_failing_does_not_hide_the_rest(monkeypatch):
    calls = stub(monkeypatch, {ne.ESSEN_FLUG_DUS_DAY: RuntimeError("down"), ne.ESSEN_RUHIG: [{"NAME": "Stadtwald"}]})
    d = ne.get_noise_extra(51.42, 7.02)
    assert d["ruhiges_gebiet"]["name"] == "Stadtwald" and d["flug"] is None and d["errors"] == {"flug_dus_day": "down"}
    assert set(calls) == {ne.ESSEN_FLUG_DUS_DAY, ne.ESSEN_FLUG_DUS_NIGHT, ne.ESSEN_FLUG_EMH_DAY, ne.ESSEN_RUHIG}
