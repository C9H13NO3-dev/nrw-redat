import pytest

from redat.auth import passwords as pw


def test_hash_and_verify_roundtrip():
    h = pw.hash_password("korrekt-pferd-batterie")
    assert h.startswith("scrypt$32768$8$1$") and h.count("$") == 5
    assert pw.verify_password("korrekt-pferd-batterie", h)
    assert not pw.verify_password("korrekt-pferd-batteri", h)


def test_hashes_are_salted():
    assert pw.hash_password("abcdefgh") != pw.hash_password("abcdefgh")


def test_verify_parses_parameters_from_the_stored_string():
    h = pw.hash_password("abcdefgh", n=2 ** 14)
    assert h.startswith("scrypt$16384$8$1$") and pw.verify_password("abcdefgh", h)


def test_verify_never_raises_on_garbage():
    for bad in ("", "plain", "scrypt$x$8$1$a$b", "scrypt$16384$8$1$!!!$???", None):
        assert pw.verify_password("abcdefgh", bad) is False


def test_policy():
    with pytest.raises(pw.PasswordPolicyError, match="mindestens 8"):
        pw.check_policy("kurz")
    with pytest.raises(pw.PasswordPolicyError, match="höchstens 200"):
        pw.check_policy("x" * 201)
    with pytest.raises(pw.PasswordPolicyError):
        pw.hash_password("kurz")
    pw.check_policy("test123!")
