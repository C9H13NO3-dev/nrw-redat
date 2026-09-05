"""Manual end-to-end smoke for the analyzer page (needs a running instance, default :8200).

    .venv/bin/python scripts/smoke_analyze.py
    .venv/bin/python scripts/smoke_analyze.py --base-url http://192.168.188.64:8200
    .venv/bin/python scripts/smoke_analyze.py --screenshot out.png

Drives the real browser flow that the hermetic pytest suite never touches: the deep link
`/?address=...&auto=1` auto-runs the analysis, every card fetches its own
`/api/v1/section/{key}`, a successful run POSTs `/api/v1/runs` and the URL becomes the
permalink `/a/{run_id}` via `history.replaceState`. Also checks `/quellen` lists every
card from the manifest. Not collected by pytest on purpose — it hits live external
services (Geoapify, the WMS/WFS sources) through a real running REDAT instance.
"""
import argparse
import json
import os
import re
import sys

from playwright.sync_api import sync_playwright

ADDRESS = "Brückstraße 1, 45239 Essen"
DEFAULT_BASE = os.environ.get("REDAT_SMOKE_BASE_URL", "http://localhost:8200")

STATE_JS = """() => {
    const d = Alpine.$data(document.getElementById('analysis-root'));
    return {
        running: d.running,
        error: d.error,
        geocode: d.geocode,
        runIdStored: d.runIdStored,
        statuses: Object.fromEntries(Object.entries(d.sections).map(([k, v]) => [k, v && v.status])),
        messages: Object.fromEntries(Object.entries(d.sections).filter(([k, v]) => v && v.status !== 'ok').map(([k, v]) => [k, v.message])),
        manifest: d.manifest,
    };
}"""

RUN_ID_RE = re.compile(r"^/a/[A-Za-z0-9]{10}$")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=DEFAULT_BASE, help="REDAT instance to test (default %(default)s)")
    ap.add_argument("--address", default=ADDRESS)
    ap.add_argument("--screenshot")
    ap.add_argument("--timeout", type=int, default=150, help="seconds to wait for all sections")
    args = ap.parse_args()

    base = args.base_url.rstrip("/")
    url = f"{base}/?" + "&".join([f"address={args.address.replace(' ', '+')}", "auto=1"])
    failures: list[str] = []
    console: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.on("pageerror", lambda e: console.append(f"pageerror: {e}"))
        page.on("console", lambda m: console.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
        page.goto(url, wait_until="networkidle")

        page.wait_for_function(
            "() => { const d = Alpine.$data(document.getElementById('analysis-root')); return !d.running && !!d.geocode; }",
            timeout=args.timeout * 1000,
        )
        page.wait_for_timeout(500)  # let history.replaceState / the DOM settle
        state = page.evaluate(STATE_JS)
        card_count = page.evaluate(
            "() => [...document.querySelectorAll('[id^=\"card-\"]')].filter(el => getComputedStyle(el).display !== 'none').length"
        )
        current_path = page.evaluate("() => location.pathname")

        if args.screenshot:
            page.screenshot(path=args.screenshot, full_page=True)

        quellen_titles = set()
        page.goto(f"{base}/quellen", wait_until="networkidle")
        for row in page.eval_on_selector_all("table tbody tr td:first-child div", "els => els.map(e => e.textContent.trim())"):
            quellen_titles.add(row)

        browser.close()

    print(json.dumps({**state, "card_count": card_count, "current_path": current_path,
                       "quellen_card_count": len(quellen_titles)}, indent=2, ensure_ascii=False, default=str))

    manifest = state["manifest"] or []
    if state["error"]:
        failures.append(f"page error banner: {state['error']}")
    if not RUN_ID_RE.match(current_path):
        failures.append(f"URL did not become a permalink /a/<id>: {current_path!r}")
    if state["runIdStored"] and current_path != f"/a/{state['runIdStored']}":
        failures.append(f"URL {current_path!r} does not match runIdStored {state['runIdStored']!r}")
    if not manifest:
        failures.append("manifest is empty")
    if card_count != len(manifest):
        failures.append(f"expected {len(manifest)} rendered cards, found {card_count}")
    missing = [k for k in state["statuses"] if state["statuses"][k] is None]
    if missing:
        failures.append(f"sections never settled: {missing}")
    if len(quellen_titles) < len(manifest):
        failures.append(f"/quellen lists {len(quellen_titles)} cards, expected at least {len(manifest)}")
    for line in console:
        failures.append(line)

    if failures:
        print("\nFAILURES:", *failures, sep="\n  - ")
        return 1
    print(f"\nOK — analyze page smoke passed against {base}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
