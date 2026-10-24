"""Registry of machine profiles. Add new machine types here."""

from __future__ import annotations

import re

from ..reference import Profile
from . import anycubic, bambu, creality, prusa, qidi, ruida

_PROFILES: dict[str, Profile] = {p.key: p for p in [bambu.PROFILE, prusa.PROFILE, anycubic.PROFILE,
                                                 qidi.PROFILE, creality.PROFILE, ruida.PROFILE]}


def profiles() -> list[Profile]:
    return list(_PROFILES.values())


def get_profile(key: str) -> Profile:
    return _PROFILES[key]


_IMAGE_LINE = re.compile(r"^; ?[A-Za-z0-9+/=]{40,}\n", re.M)


def detection_sample(text: str) -> str:
    """The parts of a file that name its printer: the header, and the settings
    block that OrcaSlicer and PrusaSlicer write at the end. Preview-image lines
    are skipped: Creality Print puts tens of KB of them before its header."""
    if len(text) <= 70000:
        return text
    head = _IMAGE_LINE.sub("", text[:300000])[:20000]
    return head + "\n" + text[-50000:]


def detect_profile(text_sample: str) -> Profile:
    return max(_PROFILES.values(), key=lambda p: p.detect(text_sample))
