from redat.auth.throttle import LoginThrottle


def test_locks_after_five_failures_and_clears_on_success():
    t = LoginThrottle(max_failures=5, window_s=600, lock_s=60, clock=lambda: 1000.0)
    key = ("10.0.0.1", "admin")
    for _ in range(4):
        t.failure(key)
    assert t.check(key) is None
    t.failure(key)
    assert 0 < t.check(key) <= 60
    t.success(key)
    assert t.check(key) is None


def test_lock_expires_and_window_is_sliding():
    now = [1000.0]
    t = LoginThrottle(max_failures=2, window_s=100, lock_s=30, clock=lambda: now[0])
    key = ("ip", "u")
    t.failure(key); t.failure(key)
    assert t.check(key) == 30
    now[0] += 31
    assert t.check(key) is None
    t.failure(key)                      # the two old failures are outside the window now? one is within 100 s
    now[0] += 200
    t.failure(key)
    assert t.check(key) is None         # only one failure inside the window
