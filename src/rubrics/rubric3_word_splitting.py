"""
Rubric 3 -- word splitting (pada-cheda).

Word boundaries of both recitations are located in the SAME coordinate
system (position among the guru's aksharas, via the alignment). Boundaries
are then compared:
  * guru boundary the learner lacks  -> words run together
  * learner boundary the guru lacks  -> pause inside a word
Score is the F1 of boundary agreement; matching tolerates +/-1 akshara
because ASR garbling near a boundary can shift it slightly.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional
from ..phonetics.akshara import Akshara, to_words
from ..alignment.align import AlignedPair

TOLERANCE = 1


@dataclass
class Rubric3Result:
    guru_word_count: int = 0
    learner_word_count: int = 0
    boundary_errors: List[dict] = field(default_factory=list)
    error_units: int = 0
    score: float = 100.0

    def feedback(self) -> List[str]:
        if not self.boundary_errors:
            return ["Word boundaries (pada-cheda) matched the guru's rendition throughout."]
        return [e["note"] for e in self.boundary_errors]


def _word_text(word: List[Akshara]) -> str:
    return "".join(a.text for a in word)


def _boundaries(alignment: List[AlignedPair]):
    G, L, k = set(), set(), 0
    for p in alignment:
        g_sp = p.guru is not None and p.guru.text.isspace()
        l_sp = p.learner is not None and p.learner.text.isspace()
        if g_sp:
            G.add(k)
        if l_sp:
            L.add(k)
        if p.guru is not None and not g_sp:
            k += 1
    inside = lambda s: {x for x in s if 0 < x < k}
    return inside(G), inside(L)


def _match(G, L):
    free = sorted(L)
    matched, missed = 0, []
    for g in sorted(G):
        cands = [l for l in free if abs(l - g) <= TOLERANCE]
        if cands:
            free.remove(min(cands, key=lambda l: abs(l - g)))
            matched += 1
        else:
            missed.append(g)
    return matched, missed, free


def evaluate(guru_aksharas: List[Akshara], learner_aksharas: List[Akshara],
             alignment: Optional[List[AlignedPair]] = None) -> Rubric3Result:
    guru_words = [_word_text(w) for w in to_words(guru_aksharas)]
    learner_words = [_word_text(w) for w in to_words(learner_aksharas)]
    r = Rubric3Result(guru_word_count=len(guru_words), learner_word_count=len(learner_words))

    if not learner_words:
        r.boundary_errors.append({"note": "No words were recognised in the learner's recording."})
        r.error_units, r.score = max(len(guru_words), 1), 0.0
        return r

    if alignment is None:   # backward compatible: align on the fly
        from ..alignment.align import align_aksharas
        alignment = align_aksharas(guru_aksharas, learner_aksharas)

    G, L = _boundaries(alignment)
    matched, missed, extra = _match(G, L)
    Gs = sorted(G)

    for g in missed:
        i = Gs.index(g)
        if i + 1 < len(guru_words):
            r.boundary_errors.append({
                "type": "merged",
                "note": f"'{guru_words[i]}' and '{guru_words[i + 1]}' were run together without a pause."})
    for e in extra:
        wi = min(sum(1 for g in Gs if g < e), len(guru_words) - 1)
        r.boundary_errors.append({
            "type": "split",
            "note": f"A pause was inserted inside the word '{guru_words[wi]}'."})

    r.error_units = len(missed) + len(extra)
    total = len(G) + len(L)
    r.score = 100.0 if total == 0 else round(100.0 * 2 * matched / total, 1)
    return r