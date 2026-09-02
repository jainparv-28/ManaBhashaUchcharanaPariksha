from __future__ import annotations
from dataclasses import dataclass, field
from typing import List
from src.alignment.align import AlignedPair


@dataclass
class Rubric2Result:
    total_anunasika_aksharas: int = 0
    errors: List[dict] = field(default_factory=list)
    score: float = 100.0

    def feedback(self) -> List[str]:
        if not self.errors:
            return ["Nasal (anunasika) sounds were rendered correctly throughout."]
        return [
            f"{len(self.errors)} anunasika akshara(s) used the wrong nasal -- remember the "
            f"nasal must match the place of articulation of the consonant that follows it "
            f"(e.g. the 'ng' in गङ्गा is velar because ग is velar; saying गम्गा or गन्गा "
            f"substitutes a labial/dental nasal instead)."
        ]


def evaluate(alignment: List[AlignedPair], guru_aksharas) -> Rubric2Result:
    from src.phonetics import features as F
    r = Rubric2Result()
    r.total_anunasika_aksharas = sum(1 for a in guru_aksharas if F.extract_features(a).is_anunasika)
    for p in alignment:
        if p.tag == "anunasika_error":
            r.errors.append({
                "guru_akshara": p.guru.text if p.guru else None,
                "learner_akshara": p.learner.text if p.learner else None,
                "note": p.note,
            })
    denom = max(r.total_anunasika_aksharas, 1)
    r.score = max(0.0, round(100.0 * (1 - len(r.errors) / denom), 1))
    return r