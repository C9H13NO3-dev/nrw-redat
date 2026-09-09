"""Account admin over UserStore/EventStore in redat.db — for lockout recovery and maintenance.

    docker compose exec redat python scripts/users.py list
    docker compose exec redat python scripts/users.py create-admin --username admin
    docker compose exec redat python scripts/users.py reset --username anna
    docker compose exec redat python scripts/users.py disable --username anna
    docker compose exec redat python scripts/users.py enable --username anna
    docker compose exec redat python scripts/users.py prune-events --days 180

No `GEOAPIFY_API_KEY`/`get_settings()` needed — the database path comes straight from `REDAT_DATA_DIR`
(default `data`), so this runs even when the app itself refuses to start for lack of a Geoapify key.
`create-admin`/`reset` read the password from `--password-env VAR` (for scripting/tests) or prompt twice
with `getpass` and refuse on a mismatch. Exits 1 with a message on stderr for an unknown username or a
password-policy violation; 0 otherwise.
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from redat.auth.passwords import PasswordPolicyError  # noqa: E402
from redat.store.events import EventStore  # noqa: E402
from redat.store.users import InvalidUsernameError, UsernameTakenError, UserStore  # noqa: E402


def _read_password(args) -> Optional[str]:
    """The new password from --password-env, or two matching getpass prompts; None (message on stderr) on failure."""
    if args.password_env:
        pw = os.environ.get(args.password_env)
        if pw is None:
            print(f"environment variable {args.password_env!r} is not set", file=sys.stderr)
            return None
        return pw
    pw = getpass.getpass("Password: ")
    pw2 = getpass.getpass("Repeat password: ")
    if pw != pw2:
        print("passwords do not match", file=sys.stderr)
        return None
    return pw


def _find_user(users: UserStore, username: str) -> Optional[dict]:
    user = users.get_by_username(username)
    if user is None:
        print(f"unknown user {username!r}", file=sys.stderr)
    return user


def _cmd_list(users: UserStore, _args) -> int:
    rows = users.list_users()
    if not rows:
        print("no users")
        return 0
    print(f"{'id':<4} {'username':<24} {'role':<6} {'status':<10} {'created':<21} last login")
    for u in rows:
        status = "disabled" if u["disabled_at"] else "active"
        print(f"{u['id']:<4} {u['username']:<24} {u['role']:<6} {status:<10} {u['created_at']:<21} {u['last_login_at'] or '-'}")
    return 0


def _cmd_create_admin(users: UserStore, args) -> int:
    pw = _read_password(args)
    if pw is None:
        return 1
    try:
        user = users.create(args.username, pw, role="admin")
    except (InvalidUsernameError, UsernameTakenError, PasswordPolicyError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"created admin '{user['username']}' (id {user['id']})")
    return 0


def _cmd_reset(users: UserStore, args) -> int:
    user = _find_user(users, args.username)
    if user is None:
        return 1
    pw = _read_password(args)
    if pw is None:
        return 1
    try:
        users.set_password(user["id"], pw)
    except PasswordPolicyError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    users.delete_user_sessions(user["id"])
    print(f"password reset for '{user['username']}'")
    return 0


def _cmd_set_disabled(users: UserStore, args, *, disabled: bool) -> int:
    user = _find_user(users, args.username)
    if user is None:
        return 1
    users.set_disabled(user["id"], disabled)
    print(f"{'disabled' if disabled else 'enabled'} '{user['username']}'")
    return 0


def _cmd_prune_events(events: EventStore, args) -> int:
    n = events.prune(args.days)
    print(f"removed {n} events older than {args.days} days")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    default_db = Path(os.environ.get("REDAT_DATA_DIR", "data")) / "redat.db"
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--db", type=Path, default=default_db, help=f"path to redat.db (default: {default_db})")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="id, username, role, status, created, last login")
    p = sub.add_parser("create-admin", help="create a user with role=admin")
    p.add_argument("--username", required=True)
    p.add_argument("--password-env", metavar="VAR", help="read the password from this environment variable instead of prompting")
    p = sub.add_parser("reset", help="set a new password for an existing user, and log out all their sessions")
    p.add_argument("--username", required=True)
    p.add_argument("--password-env", metavar="VAR", help="read the password from this environment variable instead of prompting")
    p = sub.add_parser("disable", help="disable a user and delete their sessions")
    p.add_argument("--username", required=True)
    p = sub.add_parser("enable", help="re-enable a disabled user")
    p.add_argument("--username", required=True)
    p = sub.add_parser("prune-events", help="delete usage events older than N days")
    p.add_argument("--days", type=int, required=True)
    args = ap.parse_args(argv)

    users = UserStore(args.db)
    users.init()
    events = EventStore(args.db)
    events.init()

    if args.cmd == "list":
        return _cmd_list(users, args)
    if args.cmd == "create-admin":
        return _cmd_create_admin(users, args)
    if args.cmd == "reset":
        return _cmd_reset(users, args)
    if args.cmd == "disable":
        return _cmd_set_disabled(users, args, disabled=True)
    if args.cmd == "enable":
        return _cmd_set_disabled(users, args, disabled=False)
    if args.cmd == "prune-events":
        return _cmd_prune_events(events, args)
    return 1  # pragma: no cover — unreachable, argparse's `required=True` rejects unknown subcommands


if __name__ == "__main__":
    sys.exit(main())
