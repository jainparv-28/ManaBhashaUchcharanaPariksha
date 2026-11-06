from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional

from ..phonetics.akshara import Akshara
from ..phonetics import features as F

# A pause is never "mispronounced" as a sound. Pairing one with a real
# akshara costs more than delete+insert, so the DP never chooses it. That
# keeps the guru's word boundaries visible to Rubric 3.
WS_MISMATCH_COST = 2.0


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

    g_sp, l_sp = g.text.isspace(), l.text.isspace()
    if g_sp and l_sp:
        return AlignedPair(g, l, "match", 0.0, note="whitespace variant (ignored)")
    if g_sp != l_sp:
        return AlignedPair(g, l, "substitution", WS_MISMATCH_COST, note="pause vs sound (never aligned)")

    script = g.script or l.script or "devanagari"
    gf, lf = F.extract_features(g), F.extract_features(l)
    same_marks = (g.anusvara == l.anusvara and g.candrabindu == l.candrabindu)

    # 1. aspiration (alpaprana <-> mahaprana)
    if (len(g.consonants) == len(l.consonants) == 1 and g.vowel_sign == l.vowel_sign and same_marks):
        gc, lc = g.consonants[0], l.consonants[0]
        if F.aspiration_partner(gc, script) == lc:
            kind = "mahaprana said as alpaprana" if F.is_mahaprana(gc, script) else "alpaprana said as mahaprana"
            return AlignedPair(g, l, "aspiration_error", 0.3, note=f"'{gc}' rendered as '{lc}' ({kind})")

    # 2. same consonants, different vowel length/quality or visarga
    if g.consonants and g.consonants == l.consonants and same_marks:
        if g.vowel_sign != l.vowel_sign:
            gi, li = F.vowel_info(g.vowel_sign, script), F.vowel_info(l.vowel_sign, script)
            if gi and li:
                if gi[0] == li[0]:
                    return AlignedPair(g, l, "vowel_length_error", 0.4,
                                       note=f"vowel length: guru='{g.text}' ({gi[1]}) learner='{l.text}' ({li[1]})")
                return AlignedPair(g, l, "vowel_error", 0.7,
                                   note=f"wrong vowel: guru='{g.text}' learner='{l.text}'")
        elif g.visarga != l.visarga:
            what = "dropped" if g.visarga else "added"
            return AlignedPair(g, l, "visarga_error", 0.5,
                               note=f"visarga {what}: guru='{g.text}' learner='{l.text}'")

    # 3. anunasika (only when a nasalisation is involved on either side)
    if g.vowel_sign == l.vowel_sign and (gf.is_anunasika or lf.is_anunasika):
        g_nas = set(c for c in g.consonants if F.is_nasal(c, script))
        l_nas = set(c for c in l.consonants if F.is_nasal(c, script))
        if gf.is_anunasika != lf.is_anunasika or g_nas != l_nas:
            return AlignedPair(g, l, "anunasika_error", 0.4,
                               note=f"nasalisation differs: guru='{g.text}' learner='{l.text}'")

    # 4. dvitva (gemination)
    if gf.is_geminate or lf.is_geminate:
        if set(g.consonants) != set(l.consonants) or len(g.consonants) != len(l.consonants):
            return AlignedPair(g, l, "dvitva_error", 0.5,
                               note=f"dvitva/gemination mismatch: guru='{g.text}' learner='{l.text}'")

    # 5. conjunct
    if gf.is_conjunct or lf.is_conjunct:
        if g.consonants != l.consonants:
            return AlignedPair(g, l, "conjunct_error", 0.5,
                               note=f"sanyukta akshara mismatch: guru='{g.text}' learner='{l.text}'")

    # 6. plain substitution -- graded by how similar the sounds are
    if (len(g.consonants) == len(l.consonants) == 1 and g.vowel_sign == l.vowel_sign
            and same_marks and g.visarga == l.visarga):
        dist = F.consonant_distance(g.consonants[0], l.consonants[0], script)
        cost = dist if dist > 0 else 1.0
        why = " (similar sound)" if cost < 1.0 else ""
        return AlignedPair(g, l, "substitution", cost,
                           note=f"guru='{g.text}' learner='{l.text}'{why}")

    return AlignedPair(g, l, "substitution", 1.0, note=f"guru='{g.text}' learner='{l.text}'")


def _del_cost(a: Akshara) -> float:
    return 0.0 if a.text.isspace() else 1.0


def _ins_cost(a: Akshara) -> float:
    return 0.0 if a.text.isspace() else 1.0


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
            dp[i][j] = min(dp[i - 1][j] + _del_cost(guru[i - 1]),
                           dp[i][j - 1] + _ins_cost(learner[j - 1]),
                           dp[i - 1][j - 1] + pair.cost)

    i, j = n, m
    path: List[AlignedPair] = []
    while i > 0 or j > 0:
        if i > 0 and j > 0 and abs(dp[i][j] - (dp[i - 1][j - 1] + sub_cache[(i, j)].cost)) < 1e-9:
            path.append(sub_cache[(i, j)])
            i, j = i - 1, j - 1
        elif i > 0 and abs(dp[i][j] - (dp[i - 1][j] + _del_cost(guru[i - 1]))) < 1e-9:
            c = _del_cost(guru[i - 1])
            path.append(AlignedPair(guru[i - 1], None, "missing", c,
                                    note=f"guru='{guru[i - 1].text}' not pronounced" if c
                                    else "whitespace-only break (ignored)"))
            i -= 1
        else:
            c = _ins_cost(learner[j - 1])
            path.append(AlignedPair(None, learner[j - 1], "extra", c,
                                    note=f"learner added '{learner[j - 1].text}'" if c
                                    else "whitespace-only break (ignored)"))
            j -= 1
    path.reverse()
    return path