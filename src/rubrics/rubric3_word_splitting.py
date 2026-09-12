from __future__ import annotations
from dataclasses import dataclass, field
from typing import List
from ..phonetics.akshara import Akshara, to_words


def _word_text(word: List[Akshara]) -> str:
    return "".join(a.text for a in word)


def _levenshtein(a: str, b: str) -> int:
    n, m = len(a), len(b)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost)
    return dp[n][m]


@dataclass
class Rubric3Result:
    guru_word_count: int = 0
    learner_word_count: int = 0
    boundary_errors: List[dict] = field(default_factory=list)
    score: float = 100.0

    def feedback(self) -> List[str]:
        if not self.boundary_errors:
            return ["Word boundaries (pada-cheda) matched the guru's rendition throughout."]
        msgs = []
        for e in self.boundary_errors:
            msgs.append(e["note"])
        return msgs


def evaluate(guru_aksharas: List[Akshara], learner_aksharas: List[Akshara]) -> Rubric3Result:
    guru_words = to_words(guru_aksharas)
    learner_words = to_words(learner_aksharas)
    guru_texts = [_word_text(w) for w in guru_words]
    learner_texts = ["".join(a.text for a in w) for w in learner_words]

    r = Rubric3Result(guru_word_count=len(guru_texts), learner_word_count=len(learner_texts))

    guru_joined = "".join(guru_texts)
    learner_joined = "".join(learner_texts)

    if guru_joined != learner_joined:
        pass

    if len(guru_texts) != len(learner_texts):
        diff = len(learner_texts) - len(guru_texts)
        if diff < 0:
            r.boundary_errors.append({
                "note": f"Learner produced {abs(diff)} fewer word-groups than the guru "
                        f"({r.learner_word_count} vs {r.guru_word_count}) -- likely ran two or "
                        f"more words together without a pause (guru: {' | '.join(guru_texts)}; "
                        f"learner: {' | '.join(learner_texts)})."
            })
        else:
            r.boundary_errors.append({
                "note": f"Learner produced {diff} extra word-groups compared to the guru "
                        f"({r.learner_word_count} vs {r.guru_word_count}) -- likely paused "
                        f"mid-word (guru: {' | '.join(guru_texts)}; learner: {' | '.join(learner_texts)})."
            })
    else:
        mismatched = [i for i, (g, l) in enumerate(zip(guru_texts, learner_texts)) if g != l]
        for i in mismatched:
            if abs(len(guru_texts[i]) - len(learner_texts[i])) >= 2:
                r.boundary_errors.append({
                    "note": f"Word #{i+1} boundary looks shifted -- guru said '{guru_texts[i]}', "
                            f"learner said '{learner_texts[i]}'."
                })

    denom = max(r.guru_word_count, 1)
    r.score = max(0.0, round(100.0 * (1 - len(r.boundary_errors) / denom), 1))
    return r