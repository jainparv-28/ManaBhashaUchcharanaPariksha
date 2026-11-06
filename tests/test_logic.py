import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.phonetics.akshara import segment_aksharas
from src.alignment.align import align_aksharas
from src.pipeline import evaluate_sample
from src.asr.base import ASRBackend, ASRResult


def tags(g, l):
    return [p.tag for p in align_aksharas(segment_aksharas(g), segment_aksharas(l))]


def test_vowel_length():
    assert "vowel_length_error" in tags("कमल", "कमाल")


def test_visarga():
    assert "visarga_error" in tags("रामः", "राम")


def test_similar_sound_is_cheaper():
    pairs = align_aksharas(segment_aksharas("गज"), segment_aksharas("कज"))
    sub = [p for p in pairs if p.tag == "substitution"][0]
    assert 0 < sub.cost < 1.0


def test_plain_nasal_is_not_anunasika():
    from src.rubrics import rubric2_anunasika as R2
    g = segment_aksharas("मामा")
    assert R2.evaluate(align_aksharas(g, g), g).total_anunasika_aksharas == 0


def test_rubric2_not_all_or_nothing():
    from src.rubrics import rubric2_anunasika as R2
    g = segment_aksharas("गङ्गा तटे मामा नाम")
    l = segment_aksharas("गम्गा तटे मामा नाम")   # only the nasal in गङ्गा is wrong
    r = R2.evaluate(align_aksharas(g, l), g)
    assert 0 < r.score < 100


def test_rubric2_ignores_non_nasal_errors():
    from src.rubrics import rubric2_anunasika as R2
    g = segment_aksharas("गङ्गा तटे")
    l = segment_aksharas("गङ्गा थटे")             # aspiration slip only
    assert R2.evaluate(align_aksharas(g, l), g).score == 100.0


def test_rubric3_names_merged_words():
    r = evaluate_sample("m", guru_text="राम च कृष्ण च", learner_text="रामच कृष्ण च")
    assert r["rubric3"]["score"] < 100
    assert any("run together" in n for n in r["rubric3"]["feedback"])


def test_rubric3_ignores_punctuation():
    r = evaluate_sample("p", guru_text="राम च । कृष्ण च ॥", learner_text="राम च कृष्ण च")
    assert r["overall_score"] == 100.0


def test_english_text_is_rejected_cleanly():
    raised = None
    try:
        evaluate_sample("en", guru_text="गङ्गा तटे बुद्धः अवसत्",
                        learner_text="hello this is a test of english speech")
    except ValueError as e:
        raised = str(e)
    assert raised is not None
    assert "indic" not in raised.lower()      # no raw package error shown to users


class _Fake(ASRBackend):
    def transcribe(self, audio_path, lang="sa", initial_prompt=None):
        return ASRResult(text="गम्गा तटे", duration=2.0,
                         words=[{"word": "गम्गा", "start": 0.0, "end": 1.0, "probability": 0.9},
                                {"word": "तटे", "start": 1.0, "end": 2.0, "probability": 0.9}],
                         avg_logprob=-0.2, no_speech_prob=0.01, diagnostics={})


def test_timing_intervals_are_valid():
    r = evaluate_sample("t", guru_text="गङ्गा तटे बुद्धः अवसत्", learner_audio_path="x.webm", asr=_Fake())
    assert r["timed_errors"]
    for e in r["timed_errors"]:
        assert e["start"] is not None and e["end"] is not None
        assert e["start"] <= e["end"]


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f()
    print("test_logic.py: all tests passed")