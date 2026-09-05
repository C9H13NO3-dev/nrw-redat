"""Run one section and wrap the outcome in a fixed envelope.

run_section never raises for a known key: gating, fetch exceptions, timeouts,
None and Empty all become a status. `data` is passed through sanitize() so an
inf/nan/numpy scalar can never 500 a JSON response. Fetch runs on a daemon
thread with a timeout; abandoned workers die with the process.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from typing import Any, Optional

from redat.core import sections as _sections
from redat.core.sections import Ctx, Empty
from redat.core.tiers import enrichment_allowed
from redat.settings import get_settings

log = logging.getLogger(__name__)


def sanitize(obj: Any) -> Any:
    """Recursively make `obj` JSON-safe: non-finite floats → None, numpy scalars → Python."""
    if isinstance(obj, dict):
        return {str(k): sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize(v) for v in obj]
    if obj is None or isinstance(obj, (bool, str)):
        return obj
    if hasattr(obj, "item") and not isinstance(obj, (int, float)):
        try:
            obj = obj.item()  # numpy scalar → Python scalar
        except Exception:
            return str(obj)
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


def _gate_message(precision: Optional[str]) -> str:
    found = "straßengenau" if precision == "street" else "ortsgenau"
    return f"Adresse nur {found} — Parzellendaten benötigen eine Hausnummer"


def timeout_for(section) -> float:
    """settings.yaml `section_timeouts` overrides the registry default."""
    return float(get_settings().section_timeouts.get(section.key, section.timeout_s))


def run_section(key: str, ctx: Ctx, *, precision: Optional[str], force: bool) -> dict:
    """Return the envelope for `key`. Raises KeyError only for an unknown key."""
    section = _sections.SECTIONS[key]
    t0 = time.monotonic()
    base = {"key": section.key, "tier": section.tier, "data": None, "message": None, "source": section.source}

    def done(status: str, **fields) -> dict:
        env = {**base, "status": status, **fields}
        env["took_ms"] = int((time.monotonic() - t0) * 1000)
        return env

    # "coordinates" precision is user-supplied lat/lon — as trustworthy as a verified address.
    if not enrichment_allowed(section.tier, precision=precision, address_verified=force or precision == "coordinates"):
        env = done("gated", message=_gate_message(precision))
    else:
        # Run fetch on a daemon thread with timeout. Abandoned workers die with the process.
        result: dict = {}
        def _worker():
            try:
                result["value"] = section.fetch(ctx)
            except BaseException as e:  # noqa: BLE001 — re-raised on the caller side
                result["exc"] = e

        timeout_s = timeout_for(section)
        t = threading.Thread(target=_worker, name=f"analysis-{key}", daemon=True)
        t.start()
        t.join(timeout_s)

        if t.is_alive():
            log.warning("analysis section %s timed out after %ss", key, timeout_s)
            env = done("error", message=f"Timeout nach {timeout_s:g}s")
        elif "exc" in result:
            exc = result["exc"]
            if isinstance(exc, Empty):
                env = done("empty", message=exc.message or None)
            else:
                log.exception("analysis section %s failed", key, exc_info=exc)
                env = done("error", message=str(exc) or exc.__class__.__name__)
        else:
            data = result.get("value")
            env = done("empty") if data is None else done("ok", data=sanitize(data))

    log.info("section %s lat=%.5f lon=%.5f status=%s took_ms=%d", key, ctx.lat, ctx.lon, env["status"], env["took_ms"])
    return env
