from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Optional

DEFAULT_WEIGHTS = {"rubric1": 0.5, "rubric2": 0.25, "rubric3": 0.25}


@dataclass
class PariksaReport:
    sample_id: str
    rubric1: dict
    rubric2: dict
    rubric3: dict
    overall_score: float
    tune_note: str
    grade: str

    def to_dict(self):
        return asdict(self)


def grade_from_score(score: float) -> str:
    if score >= 90:
        return "Excellent (उत्तम)"
    if score >= 75:
        return "Good (साधु)"
    if score >= 60:
        return "Needs practice (अभ्यासं करणीयम्)"
    return "Needs significant practice (बहु अभ्यासं करणीयम्)"


def build_report(sample_id: str, r1, r2, r3, weights: Optional[dict] = None,
                  tune_matched: Optional[bool] = None) -> PariksaReport:
    w = weights or DEFAULT_WEIGHTS
    overall = (r1.score * w["rubric1"] + r2.score * w["rubric2"] + r3.score * w["rubric3"])
    overall = round(overall, 1)

    tune_note = ("Tune/intonation is not graded (per guru's guidance) -- "
                 "shown only as an optional appreciative note.")
    if tune_matched is True:
        tune_note = "Nice touch: the learner also picked up the guru's tune -- worth a short appreciative comment."
    elif tune_matched is False:
        tune_note = "Learner used a different tune than the guru -- this is fine and NOT penalised."

    return PariksaReport(
        sample_id=sample_id,
        rubric1={"name": "Syllable pronunciation (aspiration / sanyukta / dvitva)",
                 "score": r1.score, "errors": r1.errors, "feedback": r1.feedback()},
        rubric2={"name": "Anunasika (nasalisation)",
                 "score": r2.score, "errors": r2.errors, "feedback": r2.feedback()},
        rubric3={"name": "Word splitting (pada-cheda)",
                 "score": r3.score, "errors": r3.boundary_errors, "feedback": r3.feedback()},
        overall_score=overall,
        tune_note=tune_note,
        grade=grade_from_score(overall),
    )
