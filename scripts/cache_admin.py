"""Inspect or purge the persistent section/geocode cache in redat.db.

    docker compose exec redat python scripts/cache_admin.py stats
    docker compose exec redat python scripts/cache_admin.py purge --expired
    docker compose exec redat python scripts/cache_admin.py purge --section boris   # e.g. after a new BRW year
    docker compose exec redat python scripts/cache_admin.py purge --all

Safe to run against the live database: the app and this script share the WAL-mode file and every
operation is a single short transaction. Bumping a card's `cache_version` in the registry is the
code-level alternative to `purge --section` (old entries are never found again and age out).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from redat.store.cache import SectionCache  # noqa: E402


def _stats(c: SectionCache) -> int:
    s = c.stats()
    print(f"db: {s['db_path']}")
    print(f"entries: {s['entries']} (max {s['max_entries']})   bytes: {s['bytes']:,} (max {s['max_bytes']:,})   expired, not yet purged: {s['expired']}")
    print("sections:")
    for k, n in s["by_section"].items():
        print(f"  {k}: {n}")
    if s["by_namespace"]:
        print("namespaces:")
        for k, n in s["by_namespace"].items():
            print(f"  {k}: {n}")
    return 0


def _purge(c: SectionCache, args) -> int:
    if args.all:
        n, what = c.invalidate(), "all entries"
    elif args.section:
        n, what = c.invalidate(args.section), f"section {args.section}"
    else:
        n, what = c.purge_expired(), "expired entries"
    print(f"removed {n} ({what})")
    return 0


def main(argv: list[str] | None = None) -> int:
    default_db = Path(os.environ.get("REDAT_DATA_DIR", "data")) / "redat.db"
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--db", type=Path, default=default_db, help=f"path to redat.db (default: {default_db})")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("stats", help="entry counts per section/namespace, bytes, bounds")
    p = sub.add_parser("purge", help="remove entries")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--expired", action="store_true", help="only rows past their TTL")
    g.add_argument("--section", metavar="KEY", help="every cached envelope of one card")
    g.add_argument("--all", action="store_true", help="everything, including geocode/autocomplete")
    args = ap.parse_args(argv)
    if not args.db.exists():
        print(f"no database at {args.db}", file=sys.stderr)
        return 1
    c = SectionCache(0, db_path=args.db)   # ttl irrelevant for stats/purge
    try:
        return _stats(c) if args.cmd == "stats" else _purge(c, args)
    finally:
        c.close()


if __name__ == "__main__":
    sys.exit(main())
