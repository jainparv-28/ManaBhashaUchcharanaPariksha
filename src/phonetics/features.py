from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
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


@dataclass
class AksharaFeatures:
    is_conjunct: bool = False
    is_geminate: bool = False
    has_anusvara: bool = False
    has_candrabindu: bool = False
    has_nasal_consonant: bool = False
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
    f.is_anunasika = f.has_anusvara or f.has_candrabindu or f.has_nasal_consonant
    return f