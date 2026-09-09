"""Password hashing with the standard library (scrypt) — no external dependency.

Format `scrypt$<n>$<r>$<p>$<salt b64>$<hash b64>`; the parameters are parsed on verify so they can be raised
later without invalidating stored hashes. 2^15/8/1 needs ~34 MB per hash (OpenSSL's default maxmem is 32 MB,
hence the explicit `maxmem`).
"""
from __future__ import annotations

import base64
import hashlib
import secrets

MIN_LEN, MAX_LEN = 8, 200
_N, _R, _P, _DKLEN, _SALT_LEN = 2 ** 15, 8, 1, 32, 16
_MAXMEM = 128 * 1024 * 1024


class PasswordPolicyError(ValueError):
    pass


def check_policy(password: str) -> None:
    if not isinstance(password, str) or len(password) < MIN_LEN:
        raise PasswordPolicyError(f"Das Passwort muss mindestens {MIN_LEN} Zeichen lang sein.")
    if len(password) > MAX_LEN:
        raise PasswordPolicyError(f"Das Passwort darf höchstens {MAX_LEN} Zeichen lang sein.")


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=_DKLEN, maxmem=_MAXMEM)


def hash_password(password: str, *, n: int = _N, r: int = _R, p: int = _P) -> str:
    check_policy(password)
    salt = secrets.token_bytes(_SALT_LEN)
    dk = _derive(password, salt, n, r, p)
    return "$".join(("scrypt", str(n), str(r), str(p), base64.b64encode(salt).decode("ascii"), base64.b64encode(dk).decode("ascii")))


def verify_password(password: str, stored) -> bool:
    """Constant-time check; any malformed stored value is simply False."""
    try:
        algo, n, r, p, salt_b64, hash_b64 = str(stored).split("$")
        if algo != "scrypt":
            return False
        salt, expected = base64.b64decode(salt_b64, validate=True), base64.b64decode(hash_b64, validate=True)
        dk = _derive(str(password), salt, int(n), int(r), int(p))
    except (ValueError, TypeError, AttributeError):
        return False
    return secrets.compare_digest(dk, expected)
