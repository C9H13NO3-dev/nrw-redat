from redat.sources import planning_essen as pe


def stub(monkeypatch, responses: dict):
    calls = []

    def fake(layer, lat, lon, out_fields, record_count=25, base=pe.PB_BASE):
        calls.append((base, layer, out_fields))
        return {"features": [{"attributes": a} for a in responses.get((base, layer), [])]}
    monkeypatch.setattr(pe, "_query", fake)
    return calls


def test_satzung_and_sanierung_are_returned(monkeypatch):
    calls = stub(monkeypatch, {
        (pe.PB_BASE, pe.L_SATZUNG): [{"NR": "S22", "NAME": "Gestaltungssatzung  und Erhaltungssatzung  Langenbrahm - Siedlung vom 07.11.1980",
                                      "DATUM": "07.11.1980", "PLANID": "DE_05113000_S22_0_2", "BEGRUNDURL": "", "ERKLAERURL": "https://e/s22.pdf"}],
        (pe.SANIERUNG_BASE, 0): [{"ART": "Sanierung abgeschlossen, Ausgleichsbetrag", "ORT": "Werden"}],
    })
    d = pe.get_planning_signals(51.39, 7.00)
    assert d["ok"] and d["found"]
    assert d["satzung"] == [{"nr": "S22", "name": "Gestaltungssatzung und Erhaltungssatzung Langenbrahm - Siedlung vom 07.11.1980",
                             "date": "07.11.1980", "plan_id": "DE_05113000_S22_0_2", "link": {"label": "Satzung (PDF)", "url": "https://e/s22.pdf"}}]
    assert d["sanierung"] == [{"name": "Werden", "plan_type": "Sanierung abgeschlossen, Ausgleichsbetrag"}]
    assert (pe.SANIERUNG_BASE, 0, "ART,ORT") in calls and (pe.PB_BASE, pe.L_SATZUNG, "NR,NAME,DATUM,PLANID,BEGRUNDURL,ERKLAERURL") in calls


def test_nothing_found(monkeypatch):
    stub(monkeypatch, {})
    d = pe.get_planning_signals(51.39, 7.00)
    assert d["ok"] and not d["found"] and d["satzung"] == [] and d["sanierung"] == []


def test_one_failing_layer_fails_the_card(monkeypatch):
    """The eight queries run concurrently; a single failure still yields the card-level error."""
    def boom(layer, lat, lon, out_fields, record_count=25, base=pe.PB_BASE):
        if layer == pe.L_SATZUNG:
            raise RuntimeError("ArcGIS 503")
        return {"features": []}
    monkeypatch.setattr(pe, "_query", boom)
    d = pe.get_planning_signals(51.39, 7.00)
    assert d == {"ok": False, "error": "ArcGIS 503"}
