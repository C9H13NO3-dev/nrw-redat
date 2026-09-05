"""Outbound HTTP conventions: every call identifies itself (spec §13)."""
from redat import __version__
from redat.settings import get_settings


def user_agent() -> str:
    return f"nrw-redat/{__version__.split('.')[0]}.0 (+{get_settings().public_url})"


def headers() -> dict:
    return {"User-Agent": user_agent()}
