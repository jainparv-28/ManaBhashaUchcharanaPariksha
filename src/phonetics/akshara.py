from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional

from .scripts import ScriptProfile, profile_for, detect_script


@dataclass
class Akshara:
    text: str
    consonants: List[str] = field(default_factory=list)
    vowel_sign: str = ""
    is_independent_vowel: bool = False
    anusvara: bool = False
    candrabindu: bool = False
    visarga: bool = False
    script: str = ""

    def __repr__(self):
        return f"Akshara({self.text!r})"


def segment_aksharas(text: str, script: Optional[str] = None) -> List[Akshara]:
    prof: ScriptProfile = profile_for(script or text)
    chars = list(text)
    n = len(chars)
    i = 0
    out: List[Akshara] = []
    mods = prof.modifiers()

    def is_consonant(ch):
        return ch in prof.consonants

    def is_matra(ch):
        return ch in prof.vowel_signs

    def is_indep_vowel(ch):
        return ch in prof.independent_vowels

    while i < n:
        c = chars[i]

        if c.isspace():
            out.append(Akshara(text=c, script=prof.name))
            i += 1
            continue

        if is_consonant(c):
            cluster = [c]
            surface = c
            i += 1
            if prof.nukta and i < n and chars[i] == prof.nukta:
                surface += chars[i]
                i += 1
            while i + 1 < n and chars[i] == prof.halant and is_consonant(chars[i + 1]):
                surface += chars[i] + chars[i + 1]
                cluster.append(chars[i + 1])
                i += 2
                if prof.nukta and i < n and chars[i] == prof.nukta:
                    surface += chars[i]
                    i += 1
            if i < n and chars[i] == prof.halant:
                surface += chars[i]
                i += 1
                out.append(Akshara(text=surface, consonants=cluster, script=prof.name))
                continue
            vowel_sign = ""
            if i < n and is_matra(chars[i]):
                vowel_sign = chars[i]
                surface += chars[i]
                i += 1
            aks = Akshara(text=surface, consonants=cluster, vowel_sign=vowel_sign, script=prof.name)
            while i < n and chars[i] in mods:
                if chars[i] == prof.anusvara:
                    aks.anusvara = True
                elif chars[i] == prof.candrabindu:
                    aks.candrabindu = True
                elif chars[i] == prof.visarga:
                    aks.visarga = True
                aks.text += chars[i]
                i += 1
            out.append(aks)
            continue

        if is_indep_vowel(c):
            surface = c
            i += 1
            aks = Akshara(text=surface, is_independent_vowel=True, script=prof.name)
            while i < n and chars[i] in mods:
                if chars[i] == prof.anusvara:
                    aks.anusvara = True
                elif chars[i] == prof.candrabindu:
                    aks.candrabindu = True
                elif chars[i] == prof.visarga:
                    aks.visarga = True
                aks.text += chars[i]
                i += 1
            out.append(aks)
            continue

        out.append(Akshara(text=c, script=prof.name))
        i += 1

    return out


def to_words(aksharas: List[Akshara]) -> List[List[Akshara]]:
    words: List[List[Akshara]] = []
    current: List[Akshara] = []
    for a in aksharas:
        if a.text.isspace():
            if current:
                words.append(current)
                current = []
        else:
            current.append(a)
    if current:
        words.append(current)
    return words