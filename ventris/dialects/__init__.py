"""Registry of machine profiles. Add new machine types here."""

from __future__ import annotations

from ..reference import Profile
from . import anycubic, bambu, prusa, qidi, ruida

_PROFILES: dict[str, Profile] = {p.key: p for p in [bambu.PROFILE, prusa.PROFILE, anycubic.PROFILE,
                                                 qidi.PROFILE, ruida.PROFILE]}


def profiles() -> list[Profile]:
    return list(_PROFILES.values())


def get_profile(key: str) -> Profile:
    return _PROFILES[key]


def detection_sample(text: str) -> str:
    """The parts of a file that name its printer: the header, and the settings
    block that OrcaSlicer and PrusaSlicer write at the end."""
    if len(text) <= 70000:
        return text
    return text[:20000] + "\n" + text[-50000:]


def detect_profile(text_sample: str) -> Profile:
    return max(_PROFILES.values(), key=lambda p: p.detect(text_sample))
