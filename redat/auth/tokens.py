"""Opaque random tokens for sessions and invites; only their sha256 is stored."""
import hashlib
import secrets


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()
