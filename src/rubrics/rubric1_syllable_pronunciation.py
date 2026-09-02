from __future__ import annotations
from dataclasses import dataclass, field
from typing import List
from src.alignment.align import AlignedPair

RELEVANT_TAGS = {"aspiration_error", "conjunct_error", "dvitva_error", "substitution"}


@dataclass
class Rubric1Result:
    total_aksharas: int = 0
    errors: List[dict] = field(default_factory=list)
    aspiration_errors: int = 0
    conjunct_errors: int = 0
    dvitva_errors: int = 0
    other_substitutions: int = 0
    score: float = 100.0

    def feedback(self) -> List[str]:
        msgs = []
        if self.aspiration_errors:
            msgs.append(
                f"{self.aspiration_errors} akshara(s) had alpaprana/mahaprana (aspiration) "
                f"confusion -- practice minimal pairs like त/थ, क/ख, प/फ with a hand in front "
                f"of the mouth to feel the puff of air on mahaprana sounds."
            )
        if self.conjunct_errors:
            msgs.append(
                f"{self.conjunct_errors} sanyukta akshara(s) (conjuncts) were altered -- "
                f"slow the cluster down and articulate every consonant in it distinctly."
            )
        if self.dvitva_errors:
            msgs.append(
                f"{self.dvitva_errors} dvitva akshara(s) (geminated/doubled consonants) were "
                f"not held long enough or were substituted -- hold the closure briefly before release."
            )
        if not msgs:
            msgs.append("Excellent syllable-level pronunciation -- all aksharas matched the guru's rendition.")
        return msgs


def evaluate(alignment: List[AlignedPair]) -> Rubric1Result:
    r = Rubric1Result()
    scored_positions = [p for p in alignment if p.tag != "extra"]
    r.total_aksharas = len(scored_positions)
    penalty = 0.0
    for p in alignment:
        if p.tag == "aspiration_error":
            r.aspiration_errors += 1
            penalty += p.cost
            r.errors.append(_err(p))
        elif p.tag == "conjunct_error":
            r.conjunct_errors += 1
            penalty += p.cost
            r.errors.append(_err(p))
        elif p.tag == "dvitva_error":
            r.dvitva_errors += 1
            penalty += p.cost
            r.errors.append(_err(p))
        elif p.tag == "substitution":
            r.other_substitutions += 1
            penalty += p.cost
            r.errors.append(_err(p))
        elif p.tag in ("missing", "extra"):
            penalty += p.cost
            r.errors.append(_err(p))

    denom = max(r.total_aksharas, 1)
    r.score = max(0.0, round(100.0 * (1 - penalty / denom), 1))
    return r


def _err(p: AlignedPair) -> dict:
    return {
        "type": p.tag,
        "guru_akshara": p.guru.text if p.guru else None,
        "learner_akshara": p.learner.text if p.learner else None,
        "note": p.note,
    }