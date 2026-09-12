import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.pipeline import evaluate_sample
from src.asr.base import ASRBackend, ASRResult


def test_pipeline_perfect():
    r = evaluate_sample("demo_perfect", guru_text="गङ्गा जलं पवित्रम् अस्ति", learner_text="गङ्गा जलं पवित्रम् अस्ति")
    assert r["overall_score"] == 100.0
    assert "stages" in r
    assert set(["asr", "normalization", "script_detection", "segmentation",
                "alignment", "rubric1", "rubric2", "rubric3", "scoring"]).issubset(r["stages"].keys())


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
    guru = "अस्त्युत्तरस्यां दिशि देवतात्मा हिमालयो नाम नगाधिराजः ।"
    romanized = "Ṣītāṁ Ṣāṁ Ṣīyāṁ Ṣīdīvatātmā Ṣīmālayonā mānāgādī rājāḥ"
    r = evaluate_sample("demo_romanized", guru_text=guru, learner_text=romanized)
    assert r["used_transliteration_fallback"] is True
    assert r["script"] == "devanagari"
    from src.phonetics.scripts import detect_script
    assert detect_script(r["learner_text"]) == "devanagari"


def test_pipeline_no_false_positive_fallback():
    r = evaluate_sample("demo_normal", guru_text="गङ्गा तटे बुद्धः अवसत्",
                         learner_text="गङ्गा तटे बुद्धः अवसत्")
    assert r["used_transliteration_fallback"] is False


def test_pipeline_newline_in_reference_text_is_free():
    # Real reference texts (typed from the docx) often have a line break
    # between padas; ASR output never produces newlines. This must not
    # cost any phoneme-error points.
    guru = "राम च कृष्ण च\nपाण्डवाः पञ्च"
    learner_ok = "राम च कृष्ण च पाण्डवाः पञ्च"  # ASR-style, no newline
    r = evaluate_sample("demo_newline_ok", guru_text=guru, learner_text=learner_ok)
    assert r["overall_score"] == 100.0, r

    learner_bad = "राम च कृष्ण च पाण्दवाः पञ्च"  # ण->द real error, unrelated to newline
    r2 = evaluate_sample("demo_newline_bad", guru_text=guru, learner_text=learner_bad)
    assert r2["overall_score"] < 100.0, r2


class _FakeEchoWhisper(ASRBackend):
    """Simulates the ORIGINAL bug: an ASR backend that (because it was
    conditioned on the exact guru text as a prompt) echoes the prompt back
    verbatim on a low-confidence/quiet recording, regardless of what was
    actually said."""
    def __init__(self, echo_text):
        self.echo_text = echo_text

    def transcribe(self, audio_path, lang="sa", initial_prompt=None):
        return ASRResult(
            text=self.echo_text,
            avg_logprob=-1.8,       # very low confidence
            no_speech_prob=0.75,    # backend barely thinks there's speech
            prompt_echo_suspected=True,
            diagnostics={"low_confidence": True},
        )


def test_pipeline_flags_suspected_prompt_echo():
    guru = "गङ्गा तटे बुद्धः अवसत्"
    fake_backend = _FakeEchoWhisper(echo_text=guru)
    r = evaluate_sample("demo_echo", guru_text=guru, learner_audio_path="fake.weba",
                         asr=fake_backend, asr_lang="sa")
    # The transcript matches perfectly (that's the bug's symptom), but the
    # pipeline MUST flag it rather than silently reporting a trustworthy 100.
    assert r["overall_score"] == 100.0
    assert r["asr_flagged"] is True
    assert r["asr_flag_reason"]
    assert r["stages"]["asr"]["flagged"] is True


class _FakeGoodWhisper(ASRBackend):
    """A confident backend that actually transcribes real (differing) audio content."""
    def __init__(self, text):
        self.text = text

    def transcribe(self, audio_path, lang="sa", initial_prompt=None):
        return ASRResult(text=self.text, avg_logprob=-0.2, no_speech_prob=0.02,
                          prompt_echo_suspected=False, diagnostics={"low_confidence": False})


def test_pipeline_does_not_flag_confident_transcript():
    guru = "गङ्गा तटे बुद्धः अवसत्"
    fake_backend = _FakeGoodWhisper(text="गम्गा तटे बुद्धः अवसत्")  # genuine anunasika error
    r = evaluate_sample("demo_confident", guru_text=guru, learner_audio_path="fake.weba",
                         asr=fake_backend, asr_lang="sa")
    assert r["asr_flagged"] is False
    assert r["overall_score"] < 100.0
    assert r["rubric2"]["score"] < 100.0


if __name__ == "__main__":
    test_pipeline_perfect()
    test_pipeline_with_errors()
    test_pipeline_word_split()
    test_pipeline_romanized_asr_fallback()
    test_pipeline_no_false_positive_fallback()
    test_pipeline_newline_in_reference_text_is_free()
    test_pipeline_flags_suspected_prompt_echo()
    test_pipeline_does_not_flag_confident_transcript()
    print("test_pipeline.py: all tests passed")
