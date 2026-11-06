from __future__ import annotations
from dataclasses import dataclass, field
from typing import List
from ..alignment.align import AlignedPair
from ..phonetics import features as F

PLAIN_NASAL_WEIGHT = 0.5   # a lone म/न/ण counts half as much as a true anunasika


@dataclass
class Rubric2Result:
    total_anunasika_aksharas: int = 0     # anusvara / candrabindu / nasal conjuncts
    total_plain_nasals: int = 0           # ordinary म न ण ... aksharas
    total_weight: float = 0.0
    penalty: float = 0.0
    errors: List[dict] = field(default_factory=list)
    score: float = 100.0

    def feedback(self) -> List[str]:
        if self.total_weight == 0:
            return ["This text has no nasal sounds to check."]
        if not self.errors:
            return ["Nasal (anunasika) sounds were rendered correctly throughout."]
        return [
            f"{len(self.errors)} nasal sound(s) were dropped, missed or replaced by a different nasal -- "
            f"the nasal must match the place of articulation of the consonant that follows it "
            f"(e.g. the 'ng' in गङ्गा is velar because ग is velar; saying गम्गा or गन्गा "
            f"substitutes a labial/dental nasal instead)."
        ]


def _nasal_set(a) -> set:
    script = a.script or "devanagari"
    return {c for c in a.consonants if F.is_nasal(c, script)}


def _weight(a) -> float:
    if a is None or a.text.isspace():
        return 0.0
    if F.extract_features(a).is_anunasika:
        return 1.0
    if _nasal_set(a):
        return PLAIN_NASAL_WEIGHT
    return 0.0


def _nasal_kept(g, l) -> bool:
    """Did the learner's akshara preserve the guru akshara's nasalisation?
    Other differences (vowel, aspiration, ...) are NOT this rubric's business."""
    if l is None or l.text.isspace():
        return False
    g_n, l_n = _nasal_set(g), _nasal_set(l)
    if F.extract_features(g).is_anunasika:
        if not F.extract_features(l).is_anunasika:
            return False                       # nasalisation lost
        if g_n and l_n and g_n != l_n:
            return False                       # wrong nasal (ङ -> म ...)
        return True
    return bool(g_n) and g_n <= l_n            # plain nasal must stay the same nasal


def evaluate(alignment: List[AlignedPair], guru_aksharas=None) -> Rubric2Result:
    r = Rubric2Result()
    for p in alignment:
        w = _weight(p.guru)
        if w == 0:
            continue
        r.total_weight += w
        if w == 1.0:
            r.total_anunasika_aksharas += 1
        else:
            r.total_plain_nasals += 1
        if p.tag == "match" or _nasal_kept(p.guru, p.learner):
            continue
        r.penalty += w
        r.errors.append({
            "guru_akshara": p.guru.text,
            "learner_akshara": p.learner.text if p.learner else None,
            "note": p.note or p.tag,
        })
    r.score = 100.0 if r.total_weight == 0 else max(0.0, round(100.0 * (1 - r.penalty / r.total_weight), 1))
    return r