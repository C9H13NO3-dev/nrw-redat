"""Import the numpy-backed C-extension stack once, in the main thread, before any section thread runs.

Why: every card's `fetch` imports its source module lazily on a daemon thread (`core/envelope.py`), and
a page load fires ~26 of those threads at once. In a fresh process several of them then perform the
*first* import of numpy / shapely / pyproj / geopandas concurrently. CPython's per-module import locks
detect the resulting cycle (numpy.__init__ → numpy._core → _multiarray_umath while another thread holds
`numpy._core.multiarray` via shapely's `import_array()`), break it, and the loser sees a half-initialised
module: `ImportError: cannot import name '__cpu_features__' from partially initialized module
'numpy._core._multiarray_umath'`. Worse, the broken partial module stays in `sys.modules`, so every later
import in that process fails too — the whole container has to be restarted. Seen live 2026-09-06
(`/a/khchav5vji`); reproduced 3/6 runs in the production image with 8 threads importing concurrently,
0/6 once the stack was imported in the main thread first.

`warm_geo_stack()` is called synchronously from `create_app()` — i.e. at `redat.app` import time, in the
main thread, before uvicorn accepts a request — so the section threads only ever find fully initialised
modules. Cost: ~1 s of startup, which the process pays once.
"""
from __future__ import annotations

import importlib
import logging
import time

log = logging.getLogger(__name__)

# Order matters only for readability; numpy first, then everything that binds to it at import time.
GEO_STACK: tuple[str, ...] = ("numpy", "pyproj", "shapely", "shapely.geometry", "shapely.ops", "geopandas")


def warm_geo_stack() -> tuple[str, ...]:
    """Import every module in GEO_STACK in the calling thread and return the names. Raises on failure —
    a process that cannot import numpy cannot serve any parcel card, so it should not start quietly."""
    t0 = time.monotonic()
    for name in GEO_STACK:
        importlib.import_module(name)
    log.info("geo stack warmed in %d ms (%s)", int((time.monotonic() - t0) * 1000), ", ".join(GEO_STACK))
    return GEO_STACK
