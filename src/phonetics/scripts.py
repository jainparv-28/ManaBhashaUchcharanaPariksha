from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Optional, Set, Tuple


@dataclass
class ScriptProfile:
    name: str
    consonants: Set[str]
    vowel_signs: Set[str]
    independent_vowels: Set[str]
    halant: str
    anusvara: str
    candrabindu: str
    visarga: str
    nukta: Optional[str]
    avagraha: Optional[str]
    varga: Dict[str, Tuple[str, int]]
    nasal_consonants: Set[str]
    alpaprana: Set[str]
    mahaprana: Set[str]
    aspiration_pair: Dict[str, str]
    homorganic_nasal: Dict[str, str]

    def modifiers(self) -> Set[str]:
        mods = {self.anusvara, self.candrabindu, self.visarga}
        if self.nukta:
            mods.add(self.nukta)
        if self.avagraha:
            mods.add(self.avagraha)
        return mods


_DEVA_VARGA = {
    "क": ("velar", 1), "ख": ("velar", 2), "ग": ("velar", 3), "घ": ("velar", 4), "ङ": ("velar", 5),
    "च": ("palatal", 1), "छ": ("palatal", 2), "ज": ("palatal", 3), "झ": ("palatal", 4), "ञ": ("palatal", 5),
    "ट": ("retroflex", 1), "ठ": ("retroflex", 2), "ड": ("retroflex", 3), "ढ": ("retroflex", 4), "ण": ("retroflex", 5),
    "त": ("dental", 1), "थ": ("dental", 2), "द": ("dental", 3), "ध": ("dental", 4), "न": ("dental", 5),
    "प": ("labial", 1), "फ": ("labial", 2), "ब": ("labial", 3), "भ": ("labial", 4), "म": ("labial", 5),
}
_DEVA_ALPAPRANA = {"क", "ग", "च", "ज", "ट", "ड", "त", "द", "प", "ब"}
_DEVA_MAHAPRANA = {"ख", "घ", "छ", "झ", "ठ", "ढ", "थ", "ध", "फ", "भ"}
_DEVA_ASPIRATION_PAIR = {
    "क": "ख", "ख": "क", "ग": "घ", "घ": "ग", "च": "छ", "छ": "च", "ज": "झ", "झ": "ज",
    "ट": "ठ", "ठ": "ट", "ड": "ढ", "ढ": "ड", "त": "थ", "थ": "त", "द": "ध", "ध": "द",
    "प": "फ", "फ": "प", "ब": "भ", "भ": "ब",
}
_DEVA_NASALS = {"ङ", "ञ", "ण", "न", "म"}
_DEVA_HOMORGANIC = {"velar": "ङ", "palatal": "ञ", "retroflex": "ण", "dental": "न", "labial": "म"}

DEVANAGARI = ScriptProfile(
    name="devanagari",
    consonants=(set(chr(c) for c in range(0x0915, 0x0939 + 1))
                | set("\u0958\u0959\u095A\u095B\u095C\u095D\u095E\u095F\u0929\u0931\u0933\u0934")),
    vowel_signs=set("\u093E\u093F\u0940\u0941\u0942\u0943\u0944\u0946\u0947\u0948\u094A\u094B\u094C\u0962\u0963"),
    independent_vowels=set("\u0904\u0905\u0906\u0907\u0908\u0909\u090A\u090B\u090C\u090D\u090E\u090F"
                            "\u0910\u0911\u0912\u0913\u0914\u0960\u0961"),
    halant="\u094D",
    anusvara="\u0902",
    candrabindu="\u0901",
    visarga="\u0903",
    nukta="\u093C",
    avagraha="\u093D",
    varga=_DEVA_VARGA,
    nasal_consonants=_DEVA_NASALS,
    alpaprana=_DEVA_ALPAPRANA,
    mahaprana=_DEVA_MAHAPRANA,
    aspiration_pair=_DEVA_ASPIRATION_PAIR,
    homorganic_nasal=_DEVA_HOMORGANIC,
)

_TEL_VARGA = {
    "క": ("velar", 1), "ఖ": ("velar", 2), "గ": ("velar", 3), "ఘ": ("velar", 4), "ఙ": ("velar", 5),
    "చ": ("palatal", 1), "ఛ": ("palatal", 2), "జ": ("palatal", 3), "ఝ": ("palatal", 4), "ఞ": ("palatal", 5),
    "ట": ("retroflex", 1), "ఠ": ("retroflex", 2), "డ": ("retroflex", 3), "ఢ": ("retroflex", 4), "ణ": ("retroflex", 5),
    "త": ("dental", 1), "థ": ("dental", 2), "ద": ("dental", 3), "ధ": ("dental", 4), "న": ("dental", 5),
    "ప": ("labial", 1), "ఫ": ("labial", 2), "బ": ("labial", 3), "భ": ("labial", 4), "మ": ("labial", 5),
}
_TEL_ALPAPRANA = {"క", "గ", "చ", "జ", "ట", "డ", "త", "ద", "ప", "బ"}
_TEL_MAHAPRANA = {"ఖ", "ఘ", "ఛ", "ఝ", "ఠ", "ఢ", "థ", "ధ", "ఫ", "భ"}
_TEL_ASPIRATION_PAIR = {
    "క": "ఖ", "ఖ": "క", "గ": "ఘ", "ఘ": "గ", "చ": "ఛ", "ఛ": "చ", "జ": "ఝ", "ఝ": "జ",
    "ట": "ఠ", "ఠ": "ట", "డ": "ఢ", "ఢ": "డ", "త": "థ", "థ": "త", "ద": "ధ", "ధ": "ద",
    "ప": "ఫ", "ఫ": "ప", "బ": "భ", "భ": "బ",
}
_TEL_NASALS = {"ఙ", "ఞ", "ణ", "న", "మ"}
_TEL_HOMORGANIC = {"velar": "ఙ", "palatal": "ఞ", "retroflex": "ణ", "dental": "న", "labial": "మ"}

TELUGU = ScriptProfile(
    name="telugu",
    consonants=set(chr(c) for c in range(0x0C15, 0x0C39 + 1)) | {"\u0C58", "\u0C59", "\u0C5A"},
    vowel_signs=set("\u0C3E\u0C3F\u0C40\u0C41\u0C42\u0C43\u0C44\u0C46\u0C47\u0C48\u0C4A\u0C4B\u0C4C\u0C62\u0C63"),
    independent_vowels=set("\u0C05\u0C06\u0C07\u0C08\u0C09\u0C0A\u0C0B\u0C0C\u0C0E\u0C0F\u0C10"
                            "\u0C12\u0C13\u0C14\u0C60\u0C61"),
    halant="\u0C4D",
    anusvara="\u0C02",
    candrabindu="\u0C01",
    visarga="\u0C03",
    nukta=None,
    avagraha=None,
    varga=_TEL_VARGA,
    nasal_consonants=_TEL_NASALS,
    alpaprana=_TEL_ALPAPRANA,
    mahaprana=_TEL_MAHAPRANA,
    aspiration_pair=_TEL_ASPIRATION_PAIR,
    homorganic_nasal=_TEL_HOMORGANIC,
)

PROFILES: Dict[str, ScriptProfile] = {"devanagari": DEVANAGARI, "telugu": TELUGU}


def detect_script(text: str) -> str:
    for ch in text:
        cp = ord(ch)
        if 0x0900 <= cp <= 0x097F:
            return "devanagari"
        if 0x0C00 <= cp <= 0x0C7F:
            return "telugu"
    return "unknown"


def profile_for(text_or_script: str) -> ScriptProfile:
    if text_or_script in PROFILES:
        return PROFILES[text_or_script]
    script = detect_script(text_or_script)
    if script not in PROFILES:
        raise ValueError(
            f"Could not detect a supported script (Devanagari or Telugu) in: {text_or_script!r}"
        )
    return PROFILES[script]
