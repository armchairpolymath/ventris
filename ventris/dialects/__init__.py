"""Registry of machine profiles. Add new machine types here."""

from __future__ import annotations

from ..reference import Profile
from . import bambu, prusa, ruida

_PROFILES: dict[str, Profile] = {p.key: p for p in [bambu.PROFILE, prusa.PROFILE, ruida.PROFILE]}


def profiles() -> list[Profile]:
    return list(_PROFILES.values())


def get_profile(key: str) -> Profile:
    return _PROFILES[key]


def detect_profile(text_sample: str) -> Profile:
    return max(_PROFILES.values(), key=lambda p: p.detect(text_sample))
