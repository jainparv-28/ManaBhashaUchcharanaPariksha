from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional

from ..phonetics.akshara import Akshara
from ..phonetics import features as F


@dataclass
class AlignedPair:
    guru: Optional[Akshara]
    learner: Optional[Akshara]
    tag: str
    cost: float
    note: str = ""


def _classify_substitution(g: Akshara, l: Akshara) -> AlignedPair:
    if g.text == l.text:
        return AlignedPair(g, l, "match", 0.0)

    # Whitespace-vs-whitespace: any run of whitespace (space, newline, tab)
    # is phonetically and orthographically insignificant -- it's a word/line
    # boundary marker, not an akshara the learner mispronounced. Guru texts
    # are often typed with line breaks between padas while ASR output uses
    # plain spaces, so this must never be scored as a substitution error.
    if g.text.isspace() and l.text.isspace():
        return AlignedPair(g, l, "match", 0.0, note="whitespace variant (ignored)")

    # Exactly ONE side is whitespace: the aligner is pairing a real akshara
    # against a pause/word-boundary. This is never a genuine aspiration,
    # anunasika, gemination, or conjunct mix-up -- it's really a deletion
    # (guru akshara never pronounced) or an insertion (learner said
    # something extra at what should have been a pause). Left unguarded,
    # this used to fall through into the feature-based classifiers below,
    # which produced nonsense like an "anunasika_error" between a space and
    # a consonant, and it also broke time-interval reporting: a whitespace
    # akshara has no word index (see phonetics.akshara.word_index_map), so
    # these pairs always came back with start/end = null instead of being
    # routed through the "missing" gap-fill logic in alignment/timing.py.
    if g.text.isspace() != l.text.isspace():
        if g.text.isspace():
            return AlignedPair(None, l, "extra", 1.0,
                                note=f"learner added '{l.text}' where the guru's text had a pause")
        return AlignedPair(g, None, "missing", 1.0,
                            note=f"guru='{g.text}' not pronounced (aligned to a pause in the transcript)")

    script = g.script or l.script or "devanagari"

    gf, lf = F.extract_features(g), F.extract_features(l)

    if (len(g.consonants) == len(l.consonants) == 1 and g.vowel_sign == l.vowel_sign
            and g.anusvara == l.anusvara and g.candrabindu == l.candrabindu):
        gc, lc = g.consonants[0], l.consonants[0]
        if F.aspiration_partner(gc, script) == lc:
            kind = "mahaprana said as alpaprana" if F.is_mahaprana(gc, script) else "alpaprana said as mahaprana"
            return AlignedPair(g, l, "aspiration_error", 0.3,
                                note=f"'{gc}' rendered as '{lc}' ({kind})")

    if g.vowel_sign == l.vowel_sign and (gf.is_anunasika != lf.is_anunasika or (
        gf.has_nasal_consonant and lf.has_nasal_consonant and
        g.consonants and l.consonants and
        set(c for c in g.consonants if F.is_nasal(c, script)) != set(c for c in l.consonants if F.is_nasal(c, script))
    )):
        return AlignedPair(g, l, "anunasika_error", 0.4,
                            note=f"nasalisation differs: guru='{g.text}' learner='{l.text}'")

    if gf.is_geminate or lf.is_geminate:
        if set(g.consonants) != set(l.consonants) or len(g.consonants) != len(l.consonants):
            return AlignedPair(g, l, "dvitva_error", 0.5,
                                note=f"dvitva/gemination mismatch: guru='{g.text}' learner='{l.text}'")

    if gf.is_conjunct or lf.is_conjunct:
        if g.consonants != l.consonants:
            return AlignedPair(g, l, "conjunct_error", 0.5,
                                note=f"sanyukta akshara mismatch: guru='{g.text}' learner='{l.text}'")

    return AlignedPair(g, l, "substitution", 1.0,
                        note=f"guru='{g.text}' learner='{l.text}'")


def _del_cost(guru_akshara: Akshara) -> float:
    # Deleting (i.e. the guru unit not appearing in the learner stream) a
    # pure-whitespace akshara is free -- guru texts are often typed with
    # line breaks between padas that simply don't exist as a "sound" the
    # learner could omit.
    return 0.0 if guru_akshara.text.isspace() else 1.0


def _ins_cost(learner_akshara: Akshara) -> float:
    # Same reasoning in the other direction: an extra whitespace unit in
    # the learner stream (e.g. ASR inserting a plain space where the guru
    # text had a newline) is free.
    return 0.0 if learner_akshara.text.isspace() else 1.0


def align_aksharas(guru: List[Akshara], learner: List[Akshara]) -> List[AlignedPair]:
    n, m = len(guru), len(learner)
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = dp[i - 1][0] + _del_cost(guru[i - 1])
    for j in range(1, m + 1):
        dp[0][j] = dp[0][j - 1] + _ins_cost(learner[j - 1])

    sub_cache = {}
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            pair = _classify_substitution(guru[i - 1], learner[j - 1])
            sub_cache[(i, j)] = pair
            del_cost = dp[i - 1][j] + _del_cost(guru[i - 1])
            ins_cost = dp[i][j - 1] + _ins_cost(learner[j - 1])
            sub_cost = dp[i - 1][j - 1] + pair.cost
            dp[i][j] = min(del_cost, ins_cost, sub_cost)

    i, j = n, m
    path: List[AlignedPair] = []
    while i > 0 or j > 0:
        if i > 0 and j > 0 and abs(dp[i][j] - (dp[i - 1][j - 1] + sub_cache[(i, j)].cost)) < 1e-9:
            path.append(sub_cache[(i, j)])
            i, j = i - 1, j - 1
        elif i > 0 and abs(dp[i][j] - (dp[i - 1][j] + _del_cost(guru[i - 1]))) < 1e-9:
            dcost = _del_cost(guru[i - 1])
            path.append(AlignedPair(guru[i - 1], None, "missing", dcost,
                                     note=f"guru='{guru[i - 1].text}' not pronounced"
                                     if dcost else "whitespace-only line break (ignored)"))
            i -= 1
        else:
            icost = _ins_cost(learner[j - 1])
            path.append(AlignedPair(None, learner[j - 1], "extra", icost,
                                     note=f"learner added '{learner[j - 1].text}'"
                                     if icost else "whitespace-only line break (ignored)"))
            j -= 1
    path.reverse()
    return path