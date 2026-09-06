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


def test_essen_kettwig_flug_dus_day_and_night(monkeypatch):
    calls = stub(monkeypatch, {ne.ESSEN_FLUG_DUS_DAY: [{"CATEGORY": "Lden5559", "PEGEL": "LDEN", "TEXT": "ab 55 bis 59 dB(A)"}],
                               ne.ESSEN_FLUG_DUS_NIGHT: [{"CATEGORY": "Lnight5054", "PEGEL": "LNIGHT", "TEXT": "ab 50 bis 54 dB(A)"}]})
    d = ne.get_noise_extra(51.362, 6.940)
    assert d["flug"] == {"airport": "DUS", "day": "ab 55 bis 59 dB(A)", "night": "ab 50 bis 54 dB(A)"}
    assert d["ruhiges_gebiet"] is None
    assert ne.ESSEN_RUHIG in calls and ne.BOCHUM_RUHIG not in calls


def test_essen_emh_when_dus_silent(monkeypatch):
    stub(monkeypatch, {ne.ESSEN_FLUG_EMH_DAY: [{"TEXT": "ab 55 bis 59 dB(A)"}]})
    assert ne.get_noise_extra(51.40, 6.95)["flug"] == {"airport": "EMH", "day": "ab 55 bis 59 dB(A)", "night": None}


def test_ruhiges_gebiet_essen_and_bochum(monkeypatch):
    stub(monkeypatch, {ne.ESSEN_RUHIG: [{"NAME": "Stadtwald", "BESCHREIBU": "Stadtwald"}]})
    assert ne.get_noise_extra(51.42, 7.02)["ruhiges_gebiet"] == {"name": "Stadtwald", "stadt": "Essen"}
    calls = stub(monkeypatch, {ne.BOCHUM_RUHIG: [{"NAME": "Weitmarer Holz", "ART": "Ruhiges Gebiet", "BEZIRK": "Südwest"}]})
    d = ne.get_noise_extra(51.4818, 7.2162)
    assert d["ruhiges_gebiet"] == {"name": "Weitmarer Holz", "stadt": "Bochum"} and d["flug"] is None
    assert ne.ESSEN_FLUG_DUS_DAY not in calls


def test_outside_both_cities_queries_nothing(monkeypatch):
    calls = stub(monkeypatch, {})
    assert ne.get_noise_extra(51.2199, 6.7943) == {"flug": None, "ruhiges_gebiet": None, "errors": {}} and calls == []


def test_one_layer_failing_does_not_hide_the_rest(monkeypatch):
    stub(monkeypatch, {ne.ESSEN_FLUG_DUS_DAY: RuntimeError("down"), ne.ESSEN_RUHIG: [{"NAME": "Stadtwald"}]})
    d = ne.get_noise_extra(51.42, 7.02)
    assert d["ruhiges_gebiet"]["name"] == "Stadtwald" and d["flug"] is None and d["errors"] == {"flug_dus_day": "down"}
