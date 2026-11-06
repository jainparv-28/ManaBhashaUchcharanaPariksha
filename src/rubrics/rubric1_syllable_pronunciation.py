from __future__ import annotations
from dataclasses import dataclass, field
from typing import List
from ..alignment.align import AlignedPair

_COUNTERS = {
    "aspiration_error": "aspiration_errors",
    "conjunct_error": "conjunct_errors",
    "dvitva_error": "dvitva_errors",
    "vowel_length_error": "vowel_length_errors",
    "vowel_error": "vowel_errors",
    "visarga_error": "visarga_errors",
    "substitution": "other_substitutions",
}


@dataclass
class Rubric1Result:
    total_aksharas: int = 0
    errors: List[dict] = field(default_factory=list)
    aspiration_errors: int = 0
    conjunct_errors: int = 0
    dvitva_errors: int = 0
    vowel_length_errors: int = 0
    vowel_errors: int = 0
    visarga_errors: int = 0
    other_substitutions: int = 0
    missing: int = 0
    extra: int = 0
    score: float = 100.0

    def feedback(self) -> List[str]:
        m = []
        if self.aspiration_errors:
            m.append(f"{self.aspiration_errors} akshara(s) had alpaprana/mahaprana (aspiration) confusion -- "
                     f"practise minimal pairs like त/थ, क/ख, प/फ with a hand in front of the mouth to feel the puff of air.")
        if self.conjunct_errors:
            m.append(f"{self.conjunct_errors} sanyukta akshara(s) were altered -- slow the cluster down and "
                     f"articulate every consonant distinctly.")
        if self.dvitva_errors:
            m.append(f"{self.dvitva_errors} dvitva akshara(s) were not held long enough or were substituted -- "
                     f"hold the closure briefly before release.")
        if self.vowel_length_errors:
            m.append(f"{self.vowel_length_errors} vowel(s) had the wrong length (hrasva/dirgha) -- "
                     f"make short vowels clearly short and long vowels clearly long.")
        if self.vowel_errors:
            m.append(f"{self.vowel_errors} vowel(s) were replaced by a different vowel.")
        if self.visarga_errors:
            m.append(f"{self.visarga_errors} visarga(s) were dropped or added -- end the syllable with a "
                     f"light breath (ः) where the text has one.")
        if self.other_substitutions:
            m.append(f"{self.other_substitutions} other akshara(s) were pronounced as different sounds.")
        if self.missing:
            m.append(f"{self.missing} akshara(s) were skipped.")
        if self.extra:
            m.append(f"{self.extra} extra akshara(s) were added.")
        if not m:
            m.append("Excellent syllable-level pronunciation -- all aksharas matched the guru's rendition.")
        return m


def evaluate(alignment: List[AlignedPair]) -> Rubric1Result:
    r = Rubric1Result()
    # denominator = the guru's real (non-space) aksharas
    r.total_aksharas = sum(1 for p in alignment if p.guru is not None and not p.guru.text.isspace())
    penalty = 0.0
    for p in alignment:
        if p.cost <= 0 or p.tag in ("match", "anunasika_error"):   # nasals belong to rubric 2
            continue
        penalty += p.cost
        if p.tag in _COUNTERS:
            setattr(r, _COUNTERS[p.tag], getattr(r, _COUNTERS[p.tag]) + 1)
        elif p.tag == "missing":
            r.missing += 1
        elif p.tag == "extra":
            r.extra += 1
        r.errors.append(_err(p))
    r.score = max(0.0, round(100.0 * (1 - penalty / max(r.total_aksharas, 1)), 1))
    return r


def _err(p: AlignedPair) -> dict:
    return {"type": p.tag, "guru_akshara": p.guru.text if p.guru else None,
            "learner_akshara": p.learner.text if p.learner else None, "note": p.note}