from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Tuple
from .scripts import PROFILES, profile_for


def varga_of(consonant: str, script: str) -> Optional[str]:
    v = PROFILES[script].varga.get(consonant)
    return v[0] if v else None


def is_alpaprana(consonant: str, script: str) -> bool:
    return consonant in PROFILES[script].alpaprana


def is_mahaprana(consonant: str, script: str) -> bool:
    return consonant in PROFILES[script].mahaprana


def is_nasal(consonant: str, script: str) -> bool:
    return consonant in PROFILES[script].nasal_consonants


def aspiration_partner(consonant: str, script: str) -> Optional[str]:
    return PROFILES[script].aspiration_pair.get(consonant)


_SIBILANTS = {"devanagari": set("शषस"), "telugu": set("శషస")}

# vowel sign -> (quality, length). "" is the inherent short 'a'.
_VOWELS = {
    "devanagari": {
        "": ("a", "short"), "\u093E": ("a", "long"),
        "\u093F": ("i", "short"), "\u0940": ("i", "long"),
        "\u0941": ("u", "short"), "\u0942": ("u", "long"),
        "\u0943": ("r", "short"), "\u0944": ("r", "long"),
        "\u0946": ("e", "short"), "\u0947": ("e", "long"),
        "\u0948": ("ai", "long"),
        "\u094A": ("o", "short"), "\u094B": ("o", "long"),
        "\u094C": ("au", "long"),
    },
    "telugu": {
        "": ("a", "short"), "\u0C3E": ("a", "long"),
        "\u0C3F": ("i", "short"), "\u0C40": ("i", "long"),
        "\u0C41": ("u", "short"), "\u0C42": ("u", "long"),
        "\u0C43": ("r", "short"), "\u0C44": ("r", "long"),
        "\u0C46": ("e", "short"), "\u0C47": ("e", "long"),
        "\u0C48": ("ai", "long"),
        "\u0C4A": ("o", "short"), "\u0C4B": ("o", "long"),
        "\u0C4C": ("au", "long"),
    },
}


def vowel_info(sign: str, script: str) -> Optional[Tuple[str, str]]:
    """(quality, length) of a vowel sign, or None if unknown."""
    return _VOWELS.get(script, {}).get(sign)


def consonant_distance(a: str, b: str, script: str) -> float:
    """How audibly different two consonants are (0 = identical, 1 = unrelated).
    Used to grade substitutions instead of charging a flat 1.0."""
    if a == b:
        return 0.0
    if aspiration_partner(a, script) == b:
        return 0.3
    sib = _SIBILANTS.get(script, set())
    if a in sib and b in sib:
        return 0.5
    va = PROFILES[script].varga.get(a)
    vb = PROFILES[script].varga.get(b)
    if va and vb:
        if va[0] == vb[0]:      # same place of articulation (e.g. क/ग)
            return 0.6
        if va[1] == vb[1]:      # same voicing/aspiration row, different place
            return 0.7
    return 1.0


@dataclass
class AksharaFeatures:
    is_conjunct: bool = False
    is_geminate: bool = False
    has_anusvara: bool = False
    has_candrabindu: bool = False
    has_nasal_consonant: bool = False
    has_nasal_conjunct: bool = False
    is_anunasika: bool = False
    consonant_cluster: tuple = ()


def extract_features(akshara) -> AksharaFeatures:
    script = akshara.script or "devanagari"
    cons = tuple(akshara.consonants)
    f = AksharaFeatures(consonant_cluster=cons)
    f.is_conjunct = len(cons) > 1
    f.is_geminate = len(cons) > 1 and len(set(cons)) == 1
    f.has_anusvara = akshara.anusvara
    f.has_candrabindu = akshara.candrabindu
    f.has_nasal_consonant = any(is_nasal(c, script) for c in cons)
    # A nasal followed by another consonant in the same cluster (ङ्ग, न्त, म्भ)
    # is a true anunasika; a lone म/न is just an ordinary consonant.
    f.has_nasal_conjunct = len(cons) > 1 and any(is_nasal(c, script) for c in cons[:-1])
    f.is_anunasika = f.has_anusvara or f.has_candrabindu or f.has_nasal_conjunct
    return f