from redat.store.cache import SectionCache


def _env(status): return {"key": "noise", "status": status, "data": {}}


def test_key_rounds_coordinates_to_4_places():
    c = SectionCache(60)
    assert c.key("noise", 51.38784, 7.00106, None, False) == c.key("noise", 51.38781, 7.00109, None, False)
    assert c.key("noise", 51.3878, 7.0011, None, False) != c.key("noise", 51.3878, 7.0011, None, True)
    assert c.key("boris", 51.3878, 7.0011, 400, False) != c.key("boris", 51.3878, 7.0011, 500, False)


def test_put_get_only_ok_and_empty(monkeypatch):
    c = SectionCache(60)
    k = c.key("noise", 51.3878, 7.0011, None, False)
    c.put(k, _env("error")); assert c.get(k) is None
    c.put(k, _env("gated")); assert c.get(k) is None
    c.put(k, _env("empty")); assert c.get(k)["status"] == "empty"
    c.put(k, _env("ok")); assert c.get(k)["status"] == "ok"


def test_get_returns_copy_marked_cached():
    c = SectionCache(60)
    k = c.key("noise", 1, 2, None, False)
    env = _env("ok"); c.put(k, env)
    got = c.get(k)
    assert got["cached"] is True and "cached" not in env


def test_expiry(monkeypatch):
    import redat.store.cache as m
    now = [1000.0]
    monkeypatch.setattr(m.time, "monotonic", lambda: now[0])
    c = SectionCache(10)
    k = c.key("noise", 1, 2, None, False); c.put(k, _env("ok"))
    now[0] += 9; assert c.get(k) is not None
    now[0] += 2; assert c.get(k) is None


def test_ttl_zero_disables():
    c = SectionCache(0)
    k = c.key("noise", 1, 2, None, False); c.put(k, _env("ok"))
    assert c.get(k) is None
