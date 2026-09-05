"""In-process TTL cache for section envelopes. Only ok/empty results are kept (spec §7)."""
import copy
import threading
import time
from typing import Optional

_CACHEABLE = ("ok", "empty")


class SectionCache:
    def __init__(self, ttl_s: int):
        self.ttl_s = max(0, int(ttl_s))
        self._data: dict[tuple, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def key(section: str, lat: float, lon: float, plot_size_m2, force: bool) -> tuple:
        plot = None if plot_size_m2 in (None, 0) else float(plot_size_m2)
        return (section, round(float(lat), 4), round(float(lon), 4), plot, bool(force))

    def get(self, k: tuple) -> Optional[dict]:
        if self.ttl_s == 0:
            return None
        with self._lock:
            hit = self._data.get(k)
            if hit is None:
                return None
            expires, env = hit
            if time.monotonic() >= expires:
                del self._data[k]
                return None
        out = copy.deepcopy(env)
        out["cached"] = True
        return out

    def put(self, k: tuple, envelope: dict) -> None:
        if self.ttl_s == 0 or envelope.get("status") not in _CACHEABLE:
            return
        with self._lock:
            self._data[k] = (time.monotonic() + self.ttl_s, copy.deepcopy(envelope))

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
