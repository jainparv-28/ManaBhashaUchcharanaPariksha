from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.phonetics.akshara import Akshara
from src.phonetics import features as F


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

    script = g.script or l.script or "devanagari"

    gf, lf = F.extract_features(g), F.extract_features(l)

    if (len(g.consonants) == len(l.consonants) == 1 and g.vowel_sign == l.vowel_sign
            and g.anusvara == l.anusvara and g.candrabindu == l.candrabindu):
        gc, lc = g.consonants[0], l.consonants[0]
        if F.aspiration_partner(gc, script) == lc:
            kind = "mahaprana said as alpaprana" if F.is_mahaprana(gc, script) else "alpaprana said as mahaprana"
            return AlignedPair(g, l, "aspiration_error", 0.3,
                                note=f"'{gc}' rendered as '{lc}' ({kind})")

    if gf.is_anunasika != lf.is_anunasika or (
        gf.has_nasal_consonant and lf.has_nasal_consonant and
        g.consonants and l.consonants and
        set(c for c in g.consonants if F.is_nasal(c, script)) != set(c for c in l.consonants if F.is_nasal(c, script))
    ):
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


def align_aksharas(guru: List[Akshara], learner: List[Akshara]) -> List[AlignedPair]:
    n, m = len(guru), len(learner)
    dp = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        dp[i][0] = dp[i - 1][0] + 1.0
    for j in range(1, m + 1):
        dp[0][j] = dp[0][j - 1] + 1.0

    sub_cache = {}
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            pair = _classify_substitution(guru[i - 1], learner[j - 1])
            sub_cache[(i, j)] = pair
            del_cost = dp[i - 1][j] + 1.0
            ins_cost = dp[i][j - 1] + 1.0
            sub_cost = dp[i - 1][j - 1] + pair.cost
            dp[i][j] = min(del_cost, ins_cost, sub_cost)

    i, j = n, m
    path: List[AlignedPair] = []
    while i > 0 or j > 0:
        if i > 0 and j > 0 and abs(dp[i][j] - (dp[i - 1][j - 1] + sub_cache[(i, j)].cost)) < 1e-9:
            path.append(sub_cache[(i, j)])
            i, j = i - 1, j - 1
        elif i > 0 and abs(dp[i][j] - (dp[i - 1][j] + 1.0)) < 1e-9:
            path.append(AlignedPair(guru[i - 1], None, "missing", 1.0,
                                     note=f"guru='{guru[i - 1].text}' not pronounced"))
            i -= 1
        else:
            path.append(AlignedPair(None, learner[j - 1], "extra", 1.0,
                                     note=f"learner added '{learner[j - 1].text}'"))
            j -= 1
    path.reverse()
    return path