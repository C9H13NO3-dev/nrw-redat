"""Envelope contract: run_section always returns {key,tier,status,data,message,source,took_ms}."""
import math
import time

import pytest

from redat.core import sections as S
from redat.core.envelope import run_section, sanitize

ENVELOPE_KEYS = {"key", "tier", "status", "data", "message", "source", "took_ms"}


def _register(monkeypatch, key, fetch, *, tier="parcel", timeout_s=5.0):
    from redat.core import tiers
    monkeypatch.setitem(tiers.SERVICE_TIER, key, tier)
    monkeypatch.setitem(
        S.SECTIONS, key,
        S.Section(key=key, title="T", icon="🧪", timeout_s=timeout_s, source="test", fetch=fetch),
    )


CTX = S.Ctx(lat=51.45, lon=7.01)


def test_ok_envelope_shape(monkeypatch):
    _register(monkeypatch, "t_ok", lambda ctx: {"v": 1})
    env = run_section("t_ok", CTX, precision="building", force=False)
    assert set(env) == ENVELOPE_KEYS
    assert env["status"] == "ok" and env["data"] == {"v": 1}
    assert env["key"] == "t_ok" and env["tier"] == "parcel" and env["source"] == "test"
    assert isinstance(env["took_ms"], int) and env["took_ms"] >= 0


def test_parcel_without_precision_is_gated(monkeypatch):
    called = []
    _register(monkeypatch, "t_gate", lambda ctx: called.append(1) or {"v": 1})
    for precision in (None, "street", "suburb"):
        env = run_section("t_gate", CTX, precision=precision, force=False)
        assert env["status"] == "gated", precision
        assert env["data"] is None
        assert "Hausnummer" in env["message"]
    assert called == []


def test_street_gate_message_names_precision(monkeypatch):
    _register(monkeypatch, "t_msg", lambda ctx: {"v": 1})
    assert "straßengenau" in run_section("t_msg", CTX, precision="street", force=False)["message"]
    assert "ortsgenau" in run_section("t_msg", CTX, precision="suburb", force=False)["message"]


@pytest.mark.parametrize("precision,force", [("building", False), ("coordinates", False), (None, True), ("street", True)])
def test_parcel_bypasses(monkeypatch, precision, force):
    _register(monkeypatch, "t_bypass", lambda ctx: {"v": 1})
    assert run_section("t_bypass", CTX, precision=precision, force=force)["status"] == "ok"


def test_area_never_gated(monkeypatch):
    _register(monkeypatch, "t_area", lambda ctx: {"v": 1}, tier="area")
    assert run_section("t_area", CTX, precision=None, force=False)["status"] == "ok"


def test_fetch_raising_becomes_error(monkeypatch):
    def boom(ctx):
        raise RuntimeError("upstream 503")
    _register(monkeypatch, "t_err", boom, tier="area")
    env = run_section("t_err", CTX, precision=None, force=False)
    assert env["status"] == "error" and env["message"] == "upstream 503" and env["data"] is None


def test_timeout_becomes_error(monkeypatch):
    def slow(ctx):
        time.sleep(0.5)
        return {"v": 1}
    _register(monkeypatch, "t_slow", slow, tier="area", timeout_s=0.05)
    env = run_section("t_slow", CTX, precision=None, force=False)
    assert env["status"] == "error"
    assert env["message"] == "Timeout nach 0.05s"


def test_none_becomes_empty(monkeypatch):
    _register(monkeypatch, "t_none", lambda ctx: None, tier="area")
    env = run_section("t_none", CTX, precision=None, force=False)
    assert env["status"] == "empty" and env["data"] is None and env["message"] is None


def test_empty_exception_carries_message(monkeypatch):
    def no_dest(ctx):
        raise S.Empty("Keine Zieladressen konfiguriert")
    _register(monkeypatch, "t_empty", no_dest, tier="area")
    env = run_section("t_empty", CTX, precision=None, force=False)
    assert env["status"] == "empty" and env["message"] == "Keine Zieladressen konfiguriert"


def test_data_is_sanitized(monkeypatch):
    import numpy as np
    _register(monkeypatch, "t_san", lambda ctx: {"a": float("inf"), "b": [float("nan"), np.float64(1.5)], "c": np.int64(3), "d": np.bool_(True)}, tier="area")
    env = run_section("t_san", CTX, precision=None, force=False)
    assert env["data"] == {"a": None, "b": [None, 1.5], "c": 3, "d": True}
    assert type(env["data"]["c"]) is int and type(env["data"]["d"]) is bool


def test_unknown_key_raises():
    with pytest.raises(KeyError):
        run_section("nope", CTX, precision=None, force=False)


def test_sanitize_plain_values_untouched():
    assert sanitize({"s": "x", "i": 1, "f": 2.5, "n": None, "l": [1, "a"]}) == {"s": "x", "i": 1, "f": 2.5, "n": None, "l": [1, "a"]}
    assert math.isnan(float("nan"))  # sanity: nan really is what we feed above


def test_timeout_leaves_daemon_worker(monkeypatch):
    import threading
    event = threading.Event()
    def slow_waiter(ctx):
        event.wait()  # blocks until set
        return {"v": 1}
    _register(monkeypatch, "t_daemon", slow_waiter, tier="area", timeout_s=0.05)
    env = run_section("t_daemon", CTX, precision=None, force=False)
    assert env["status"] == "error"
    # Verify the abandoned worker is a daemon thread (dies with process).
    # At least one thread named "analysis-t_daemon" should exist and be a daemon.
    daemon_workers = [t for t in threading.enumerate() if t.name == "analysis-t_daemon" and t.daemon]
    assert len(daemon_workers) > 0, "Timed-out worker should be a daemon thread"
    # Clean up: signal the worker to exit.
    event.set()
    # Give the thread a moment to finish.
    time.sleep(0.05)


def test_settings_timeout_override(monkeypatch):
    from redat.core import envelope as E
    from redat.core.sections import SECTIONS
    monkeypatch.setattr(E, "get_settings", lambda: type("S", (), {"section_timeouts": {"noise": 1.5}})())
    assert E.timeout_for(SECTIONS["noise"]) == 1.5
    assert E.timeout_for(SECTIONS["boris"]) == SECTIONS["boris"].timeout_s
