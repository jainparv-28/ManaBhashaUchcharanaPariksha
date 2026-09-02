import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.pipeline import evaluate_sample


def test_pipeline_perfect():
    r = evaluate_sample("demo_perfect", guru_text="गङ्गा जलं पवित्रम् अस्ति", learner_text="गङ्गा जलं पवित्रम् अस्ति")
    assert r["overall_score"] == 100.0


def test_pipeline_with_errors():
    r = evaluate_sample(
        "demo_errors",
        guru_text="गङ्गा तटे बुद्धः अवसत्",
        learner_text="गम्गा थटे बुद्दः अवसत्",
    )
    assert r["overall_score"] < 100.0
    assert r["rubric1"]["score"] < 100.0
    assert r["rubric2"]["score"] < 100.0


def test_pipeline_word_split():
    r = evaluate_sample(
        "demo_split",
        guru_text="राम च कृष्ण च",
        learner_text="रामच कृष्णच",
    )
    assert r["rubric3"]["score"] < 100.0


def test_pipeline_romanized_asr_fallback():
    # Reproduces the real-world failure: Whisper sometimes romanizes
    # Sanskrit/Telugu instead of transcribing in native script, even with
    # language="sa" set. The pipeline must transliterate and still produce
    # a (flagged, lower-confidence) score instead of crashing.
    guru = "अस्त्युत्तरस्यां दिशि देवतात्मा हिमालयो नाम नगाधिराजः ।"
    romanized = "Ṣītāṁ Ṣāṁ Ṣīyāṁ Ṣīdīvatātmā Ṣīmālayonā mānāgādī rājāḥ"
    r = evaluate_sample("demo_romanized", guru_text=guru, learner_text=romanized)
    assert r["used_transliteration_fallback"] is True
    assert r["script"] == "devanagari"
    # transliteration must have actually produced Devanagari, not left it Latin
    from src.phonetics.scripts import detect_script
    assert detect_script(r["learner_text"]) == "devanagari"


def test_pipeline_no_false_positive_fallback():
    # A normal, correctly-scripted comparison must NOT trigger the fallback
    r = evaluate_sample("demo_normal", guru_text="गङ्गा तटे बुद्धः अवसत्",
                         learner_text="गङ्गा तटे बुद्धः अवसत्")
    assert r["used_transliteration_fallback"] is False


if __name__ == "__main__":
    test_pipeline_perfect()
    test_pipeline_with_errors()
    test_pipeline_word_split()
    test_pipeline_romanized_asr_fallback()
    test_pipeline_no_false_positive_fallback()
    print("test_pipeline.py: all tests passed")