# Analysis PDF report — design

**Date:** 2026-09-04 · **Branch:** `feat/analysis-pdf-report` · **Status:** approved in chat, implementing

## 0. Goal

A finished `/analyze` run can be exported as a **well-formatted A4 PDF report** that
contains all the information the cards show — not a screenshot. The only image in the
report is the **Lärm map** (Tag + Nacht side by side). The PDF is downloaded from the
browser and, when the analysis belongs to a listing, filed into that listing's dossier.

Decisions taken in the brainstorm:

| Question | Decision |
|---|---|
| Destination | Download **and** dossier document (kind `report`) when `listing_id` is set |
| Lärm map | Tag (L_DEN) and Nacht (L_Night) side by side, ~600 m window, pin + scale + legend |
| Cards without data | Main body only has cards with data; appendix table "Nicht geprüft / ohne Befund" lists gated/empty/error/loading cards with their reason |
| Renderer | Jinja HTML print template → headless Chromium (`playwright`) `page.pdf()` — ReportLab and browser-print rejected |
| Data | The browser POSTs the envelopes it already holds; the server never re-runs sections |

## 1. Data flow

```
/analyze (Alpine)  ──POST /api/analysis/report──▶  routes/analysis.py
   this.sections + geocode + config                 │
                                                    ▼
                                    report/builder.build_report_context(payload)
                                        validate keys against SECTIONS, summary rows,
                                        body vs appendix split, per-section view models
                                                    │
                     report/noise_map.render_noise_maps(lat, lon)  (WMS GetMap ×2 + Pillow)
                     report/svg.boris_trend_svg(points)
                                                    │
                                                    ▼
                     templates/report/report.html (+ _{key}.html partials)  → HTML string
                                                    │
                                                    ▼
                     report/pdf.html_to_pdf(html) → bytes   (sync Playwright in a threadpool)
                                                    │
                       listing_id? → dossier.save_upload(listing, filename, "application/pdf", pdf, kind="report")
                                                    │
                                                    ▼
                      Response application/pdf, Content-Disposition attachment
```

### Request body (`POST /api/analysis/report`, JSON)

```json
{
  "address": "Brückstraße 12, 45239 Essen",
  "geocode": {"formatted_address": "…", "latitude": 51.3885, "longitude": 7.0035, "precision": "building"},
  "plot_size_m2": 450, "living_space_m2": 140, "listing_id": 123,
  "sections": {"boris": {"key": "boris", "status": "ok", "data": {...}, "message": null, "source": "…", "tier": "parcel", "took_ms": 812}, "...": {}}
}
```

Validation (422): `geocode.latitude/longitude` missing or non-numeric; any `sections` key not in
`SECTIONS`; an envelope without a `status`. Unknown extra fields are ignored. Envelope `data`
is trusted as far as *shape* goes — every partial uses `.get()`-tolerant Jinja (`d.get('x')`,
`d.x or []`) so a partially filled envelope renders a partial section rather than a 500.

### Response

- `200 application/pdf`, `Content-Disposition: attachment; filename="Standortanalyse_<slug>_<YYYY-MM-DD>.pdf"`
  where `<slug>` is the ASCII-slugified formatted address (max 60 chars).
- `X-Dossier-Document-Id: <id>` when the PDF was filed into a dossier.
- `X-Report-Warning: dossier` when `listing_id` was given but filing failed (PDF still returned).
- `503 {"detail": "PDF-Renderer nicht verfügbar"}` when Chromium cannot be launched
  (fix: `.venv/bin/playwright install chromium`; documented in HANDOVER runbook).
- `404` when `listing_id` is set but no such listing exists.

## 2. Report layout (A4 portrait, German, print CSS)

Header on every page: formatted address (left), "Standortanalyse · House Hunter" (right).
Footer: "erstellt am DD.MM.YYYY HH:MM" (left), "Seite x / y" (right) — via Chromium's
`display_header_footer` templates.

**Title page**

- H1 "Standortanalyse", formatted address, coordinates (5 decimals), precision badge
  (`building` → "hausnummerngenau", `street` → "straßengenau", `coordinates` → "Koordinaten",
  else "ortsgenau"), Grundstück/Wohnfläche when present.
- Listing block when `listing_id`: title, price, living space, rooms, portal URL (from
  `db.get_listing_by_id`).
- **Zusammenfassung** table: one row per body section, in registry order — icon + title,
  rating chip (coloured text: green/yellow/orange/red/gray mapped from `rating_color`), key
  figure. Key figures per card (`builder.SUMMARY` functions, each `data → str | None`):

| key | key figure |
|---|---|
| boris | `"{value} €/m² ({stichtag})"` |
| boris_trend | `"{first_year}: {first} → {last_year}: {last} €/m² ({pct:+.0f} %)"` |
| flood | rating text as delivered (e.g. HQ class) |
| starkregen | `"agw {max_agw}, extrem {max_extrem}"` |
| noise | `"Tag {max_den} dB · Nacht {max_ngt} dB"` |
| bergbau | rating + `"{n} Hinweise im 500 m-Planquadrat"` |
| gfnp | dominant Darstellung |
| schutzgebiete | `"{n} Gebiete ≤ 500 m"` + inside names |
| planning_essen / planning_bochum | `"{n} Verfahren"` |
| denkmal | `"{A} Bau-, {B} Bodendenkmäler ≤ 300 m"` |
| amenities | nearest supermarket / school / doctor distances |
| oepnv | `"{nearest_rail_m} m Schiene · Hbf {min} min"` |
| zensus | `"{einwohner} EW (±250 m), Ø Alter {alter}"` |
| energie | PV kWh/a + Erdwärme rating + Wärmeplanung category |
| breitband | best FTTH class + 5G |
| infrastruktur | rating + counts (`n Leitungen, n IED`) |
| air_quality | long-term NO₂/PM2.5 + current index |
| btw | winner party + share |
| commute | first two destinations with minutes |

  A card whose summary function fails (KeyError/TypeError) shows "—" — never a 500.

**Body sections** in registry order, only `status == "ok"` with non-null `data`. Each: H2
`{icon} {title}`, small grey source line, the content (tables for lists, definition rows for
scalars, the card's explanatory footnotes verbatim), `page-break-inside: avoid` on the
section wrapper (long sections — oepnv, zensus, energie — allow breaks after their tables).
Caps identical to the cards (Denkmal 12, IED 10, Schutzgebiete 5/kind, ÖPNV stops 8/lines
all/trips all).

- `noise` section additionally embeds the two map composites (see §3) with the legend.
- `boris_trend` embeds an inline SVG line chart (`svg.boris_trend_svg`) — 560×200, axis
  labels for years, min/max €/m² gridlines — plus the year table.

**Appendix "Nicht geprüft / ohne Befund"** — table: icon + title | status word
(`gated` → "gesperrt (Parzellendaten benötigen Hausnummer)", `empty` → "kein Befund",
`error` → "Fehler", `loading`/missing → "nicht geladen") | envelope `message`.
Sections absent from the payload appear as "nicht geladen".

**Quellen** — bullet list of the distinct `source` strings of body sections, plus
"Kartengrundlage: © basemap.de / BKG (dl-de/by-2-0) · Lärmkartierung: Land NRW (LANUV)".

## 3. Lärm map (`backend/report/noise_map.py`)

`render_noise_maps(lat, lon) -> dict`:

```python
{"day": "<base64 png>" | None, "night": "<base64 png>" | None,
 "legend": [{"label": "55–60 dB", "color": "#…"}, …], "attribution": str, "error": str | None}
```

- Window: 600 m × 450 m in EPSG:25832 centred on the point (`W, H = 480, 360` px → 1.25 m/px).
  BBOX via `pyproj.Transformer("EPSG:4326", "EPSG:25832", always_xy=True)`.
- Basemap: `https://sgx.geodatenzentrum.de/wms_basemapde` GetMap 1.3.0, `LAYERS=de_basemapde_web_raster_grau`,
  `CRS=EPSG:25832`, `FORMAT=image/png`.
- Noise overlay: `https://www.wms.nrw.de/umwelt/laerm` GetMap 1.3.0, `CRS=EPSG:25832`,
  `LAYERS=STR_DEN,SCB_DEN,SCS_DEN,IND_DEN,FLG_DEN` (day) / `STR_NGT,SCB_NGT,SCS_NGT,IND_NGT,FLG_NGT`
  (night), `TRANSPARENT=TRUE`, alpha-composited at 0.7 with Pillow.
- Pin: red circle r=7 with white border at the centre; scale bar 100 m (80 px) bottom-left with label;
  title "Tag (L_DEN)" / "Nacht (L_Night)" drawn top-left on a white box.
- Legend: fixed bands from the Umgebungslärm colour scheme (`LEGEND_BANDS` constant, 5 dB steps
  55…>75 for DEN, 50…>70 for NGT — shown as one combined legend labelled "dB(A)").
- Any HTTP error/timeout (10 s each) → that composite is `None` and `error` is set; the template
  renders a grey box "Karte nicht verfügbar". Basemap failure alone → overlay on white.
- Single HTTP monkeypatch point `_get_png(url, params) -> bytes`.

## 4. Backend modules

```
backend/report/__init__.py
backend/report/builder.py     build_report_context(payload) -> dict ; SUMMARY ; STATUS_LABELS ; slugify
backend/report/noise_map.py   render_noise_maps(lat, lon)
backend/report/svg.py         boris_trend_svg(points: list[tuple[int, float]]) -> str
backend/report/pdf.py         html_to_pdf(html: str) -> bytes ; RendererUnavailable
backend/report/render.py      render_report_html(ctx) -> str   (Jinja env = app_config.templates)
backend/routes/analysis.py    POST /api/analysis/report
frontend/templates/report/report.html
frontend/templates/report/_{key}.html   (planning_essen/planning_bochum share _planning.html)
frontend/static/js/analysis.js          exportPdf()
frontend/templates/analyze.html         "PDF-Bericht" button
```

`build_report_context(payload)` returns:

```python
{"address": str, "formatted_address": str, "lat": float, "lon": float, "precision_label": str,
 "plot_size_m2": ..., "living_space_m2": ..., "listing": dict | None,
 "generated_at": "04.09.2026 16:20", "summary": [{"key","icon","title","rating","rating_color","figure"}],
 "body": [{"key","icon","title","source","data"}], "appendix": [{"key","icon","title","status_label","message"}],
 "sources": [str], "noise_maps": dict | None, "boris_trend_svg": str | None}
```

`pdf.html_to_pdf`: `sync_playwright()` → `chromium.launch()` → `page.set_content(html, wait_until="load")`
→ `page.pdf(format="A4", print_background=True, margin={"top":"22mm","bottom":"18mm","left":"16mm","right":"16mm"},
display_header_footer=True, header_template=…, footer_template=…)`. Any `playwright` launch error →
`RendererUnavailable`. Called from the route via `starlette.concurrency.run_in_threadpool`.
Templates reference no external URLs (Tailwind is *not* used — a self-contained `<style>` block in
`report.html`, print-tuned) so the PDF renders offline and deterministically.

## 5. Frontend

`analyze.html`: button **"PDF-Bericht"** next to "Alle gesperrten laden"; `:disabled="running || !hasResults || exporting"`,
spinner while `exporting`. `analysis.js`:

```js
async exportPdf() {
  this.exporting = true;
  try {
    const resp = await fetch('/api/analysis/report', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({address: this.address, geocode: this.geocode, plot_size_m2: this.plotSize,
                            living_space_m2: this.livingSpace, listing_id: this.listingId, sections: this.sections})});
    if (!resp.ok) throw new Error((await resp.json()).detail || resp.statusText);
    const blob = await resp.blob();
    const name = (resp.headers.get('Content-Disposition') || '').match(/filename="([^"]+)"/)?.[1] || 'Standortanalyse.pdf';
    // object-URL download
    if (resp.headers.get('X-Dossier-Document-Id')) toast('Bericht im Dossier abgelegt');
  } catch (e) { toast('PDF-Export fehlgeschlagen: ' + e.message, 'error'); }
  finally { this.exporting = false; }
}
```

`hasResults` = at least one section with `status === 'ok'`. Sections still `loading` are sent as-is
and land in the appendix as "nicht geladen".

Dossier: `decide.html`'s document list already renders every row with its `kind`; the `kind`
select gets an `<option value="report">Bericht</option>` so manually uploaded reports can use it too.

## 6. Errors

| Failure | Behaviour |
|---|---|
| Unknown section key / bad geocode | 422, key named in `detail` |
| Summary function raises | figure "—", logged at debug |
| Partial raises during render | the whole request 500s — prevented by per-partial render tests against fixtures |
| WMS/basemap failure | grey placeholder, `noise_maps.error` shown as a small note |
| Chromium launch failure | 503 "PDF-Renderer nicht verfügbar" |
| `dossier.save_upload` raises | PDF returned, `X-Report-Warning: dossier`, error logged |

## 7. Tests

- `tests/test_report_builder.py`: ordering follows `SECTIONS`; body/appendix split for ok/empty/gated/error/loading/missing;
  unknown key → `ValueError`; every `SUMMARY` function on its fixture and on `{}` (returns str or None, never raises);
  `slugify`; precision labels; sources deduped.
- `tests/test_report_render.py`: `render_report_html` on the full fixture set contains every body title and the appendix rows;
  each partial renders on its fixture **and** on `data={}` without raising (the shape-tolerance guarantee).
- `tests/test_noise_map.py`: bbox is 600×450 m around the point; composite is 480×360 RGB PNG with `_get_png` stubbed;
  overlay failure → `None` + `error`; basemap failure → overlay on white; legend bands non-empty.
- `tests/test_report_svg.py`: SVG contains one `<polyline>` with as many points as years; empty → `None`.
- `tests/test_report_route.py` (`TestClient`, `html_to_pdf` monkeypatched to return `b"%PDF-1.4 stub"`): 200 + PDF headers +
  filename; 422 unknown key; 422 bad geocode; listing → dossier row of kind `report` created and header set; no listing → no row;
  404 unknown listing; `RendererUnavailable` → 503.
- Fixtures: `tests/fixtures/report_envelopes.json` — one real envelope per section captured from the live service for
  Werden (Brückstraße 12) so the render tests exercise real shapes.
- Live: export Werden + Kortumstraße 100 Bochum from :8011, open the PDFs (page count, title page, map present, appendix).

## 8. Docs

CLAUDE.md paragraph "Analysis PDF report (2026-09-04)"; HANDOVER work-log entry + runbook line for `playwright install chromium`.
