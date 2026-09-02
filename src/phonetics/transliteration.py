from __future__ import annotations
from typing import Optional

from src.phonetics.scripts import detect_script

_SANSCRIPT_TARGETS = None


def _targets():
    global _SANSCRIPT_TARGETS
    if _SANSCRIPT_TARGETS is None:
        from indic_transliteration import sanscript
        _SANSCRIPT_TARGETS = {
            "devanagari": sanscript.DEVANAGARI,
            "telugu": sanscript.TELUGU,
        }
    return _SANSCRIPT_TARGETS


def is_romanized(text: str) -> bool:
    if detect_script(text) != "unknown":
        return False
    return any(ch.isalpha() for ch in text)


def roman_to_script(text: str, script: str) -> str:
    try:
        from indic_transliteration.sanscript import transliterate
        from indic_transliteration import sanscript
    except ImportError as e:
        raise ImportError(
            "indic-transliteration is not installed. Run: "
            "pip install indic-transliteration --break-system-packages"
        ) from e
    target = _targets().get(script)
    if target is None:
        raise ValueError(f"No transliteration target for script '{script}'")
    return transliterate(text, sanscript.IAST, target)


def ensure_native_script(text: str, expected_script: str) -> tuple[str, bool]:
    if not is_romanized(text):
        return text, False
    return roman_to_script(text, expected_script), True