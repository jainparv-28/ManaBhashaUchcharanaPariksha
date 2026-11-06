"""
pipeline.py -- end-to-end Uchcharana Pariksha.
Stages: asr, normalization, script_detection, segmentation, alignment, timing,
quality, rubric1/2/3, scoring (all in report["stages"]).
"""
from __future__ import annotations
from typing import Optional
import re
import unicodedata

from .phonetics.akshara import segment_aksharas
from .phonetics.scripts import detect_script
from .phonetics.transliteration import ensure_native_script
from .alignment.align import align_aksharas
from .alignment.timing import map_errors_to_time
from .rubrics import rubric1_syllable_pronunciation as R1
from .rubrics import rubric2_anunasika as R2
from .rubrics import rubric3_word_splitting as R3
from .scoring import build_report
from .feedback import practice_points
from .asr.base import ASRBackend, ASRResult, NullASR

_WS_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[\u0964\u0965.,;:!?\"'\u201c\u201d\u2018\u2019()\[\]{}<>\-\u2013\u2014_/\\|*~`@#$%^&+=\u2026]")
_ZERO_WIDTH = dict.fromkeys([0x200B, 0x200C, 0x200D, 0xFEFF])

MIN_MATCH_RATIO = 0.15
MIN_COVERAGE = 0.5


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", (text or "").strip()).translate(_ZERO_WIDTH)
    text = _PUNCT_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()


def _clean_asr_words(words):
    out = []
    for w in words or []:
        tok = _normalize(str(w.get("word", "")))
        if tok:
            w = dict(w)
            w["word"] = tok
            out.append(w)
    return out


def _akshara_preview(aksharas):
    return [{"text": a.text, "consonants": a.consonants, "vowel_sign": a.vowel_sign,
             "is_independent_vowel": a.is_independent_vowel, "anusvara": a.anusvara,
             "candrabindu": a.candrabindu, "visarga": a.visarga, "script": a.script}
            for a in aksharas]


def evaluate_sample(sample_id: str, guru_text: str, learner_text: Optional[str] = None,
                    learner_audio_path: Optional[str] = None,
                    asr: Optional[ASRBackend] = None, weights: Optional[dict] = None,
                    asr_lang: str = "sa"):
    stages: dict = {}
    asr_diagnostics = None
    asr_flagged = False
    asr_flag_reason = None
    asr_words = []
    asr_duration = None

    # ---- Stage 1: ASR ----
    if learner_text is None:
        if learner_audio_path is None:
            raise ValueError("Provide either learner_text or learner_audio_path")
        backend = asr or NullASR()
        result = backend.transcribe(learner_audio_path, lang=asr_lang, initial_prompt=guru_text)
        if isinstance(result, ASRResult):
            learner_text = result.text
            asr_diagnostics = result.diagnostics
            asr_diagnostics["avg_logprob"] = result.avg_logprob
            asr_diagnostics["no_speech_prob"] = result.no_speech_prob
            asr_words = _clean_asr_words(result.words)
            asr_duration = result.duration
            if result.prompt_echo_suspected:
                asr_flagged = True
                asr_flag_reason = "ASR reported low confidence (unclear/noisy audio or possible hallucination)"
        else:
            learner_text = result
    stages["asr"] = {
        "mode": "text_supplied" if asr_diagnostics is None and learner_audio_path is None else "audio_transcribed",
        "raw_learner_text": learner_text, "diagnostics": asr_diagnostics,
        "words": asr_words, "duration": asr_duration,
        "flagged": asr_flagged, "flag_reason": asr_flag_reason,
    }

    # ---- Stage 2: normalization ----
    guru_text_norm = _normalize(guru_text)
    learner_text_norm = _normalize(learner_text)
    stages["normalization"] = {"guru_text": guru_text_norm, "learner_text": learner_text_norm}
    if not learner_text_norm:
        raise ValueError("No speech was detected in the recording. Check your microphone, "
                         "speak closer to it, and record again.")

    # ---- Stage 3: script detection ----
    guru_script = detect_script(guru_text_norm)
    if guru_script == "unknown":
        raise ValueError(f"Could not detect a supported script (Devanagari or Telugu) in guru_text "
                         f"for sample '{sample_id}': {guru_text_norm!r}")
    lang_name = "Telugu" if guru_script == "telugu" else "Sanskrit (Devanagari)"
    try:
        learner_text_final, used_transliteration_fallback = ensure_native_script(learner_text_norm, guru_script)
    except ImportError as e:
        # romanisation support missing on the server -- never show this raw to the user
        print(f"[server warning] {e}")
        raise ValueError(
            f"The recording was recognised as English / Latin text, not {lang_name}. "
            f"Please recite the selected verse in {lang_name} and try again."
        )
    stages["script_detection"] = {"guru_script": guru_script,
                                  "used_transliteration_fallback": used_transliteration_fallback,
                                  "learner_text_after_fallback": learner_text_final}

    if learner_audio_path is not None and learner_text_final == guru_text_norm and asr_diagnostics:
        if asr_diagnostics.get("low_confidence"):
            asr_flagged = True
            asr_flag_reason = (asr_flag_reason or "") + \
                " | transcript is identical to guru_text with low ASR confidence -- verify against real audio"

    # ---- Stage 4: segmentation ----
    guru_aksharas = segment_aksharas(guru_text_norm, script=guru_script)
    learner_aksharas = segment_aksharas(learner_text_final, script=guru_script)
    stages["segmentation"] = {"guru_aksharas": _akshara_preview(guru_aksharas),
                              "learner_aksharas": _akshara_preview(learner_aksharas)}

    # ---- Stage 5: alignment ----
    alignment = align_aksharas(guru_aksharas, learner_aksharas)
    alignment_preview = [
        {"guru": p.guru.text if p.guru else "-", "learner": p.learner.text if p.learner else "-",
         "tag": p.tag, "cost": p.cost, "note": p.note} for p in alignment]
    stages["alignment"] = {"pairs": alignment_preview}

    # ---- Stage 5b: timing ----
    timing_result = map_errors_to_time(alignment, learner_aksharas, guru_aksharas,
                                       asr_words=asr_words, duration=asr_duration)
    if used_transliteration_fallback and timing_result["errors"]:
        for e in timing_result["errors"]:
            e["note"] = (e["note"] or "") + " (timing based on word position after romanization fallback)"
    stages["timing"] = timing_result

    # ---- Quality gate and reliability ----
    guru_core = [a for a in guru_aksharas if not a.text.isspace()]
    learner_core = [a for a in learner_aksharas if not a.text.isspace()]
    matched = sum(1 for p in alignment
                  if p.tag == "match" and p.guru is not None and not p.guru.text.isspace())
    match_ratio = round(matched / max(len(guru_core), 1), 3)
    coverage = round(len(learner_core) / max(len(guru_core), 1), 3)

    # English / other Latin-script speech that doesn't resemble the verse: reject cleanly
    if used_transliteration_fallback and match_ratio < MIN_MATCH_RATIO:
        raise ValueError(
            f"The recording does not sound like the selected {lang_name} verse "
            f"(it was recognised as English / Latin text). Please recite the verse shown "
            f"on screen, in {lang_name}, and try again."
        )

    probs = [w["probability"] for w in asr_words if isinstance(w.get("probability"), (int, float))]
    mean_prob = round(sum(probs) / len(probs), 3) if probs else None
    timed = timing_result["errors"]
    uncertain_frac = (sum(1 for e in timed if e.get("uncertain")) / len(timed)) if timed else 0.0

    quality_warnings = []
    score_valid = True
    if match_ratio < MIN_MATCH_RATIO:
        score_valid = False
        asr_flagged = True
        quality_warnings.append(
            f"Only {match_ratio*100:.0f}% of the reference matches the recording -- it is probably "
            f"silence, noise, the wrong item, or an ASR failure. Do not trust this score.")
        asr_flag_reason = (asr_flag_reason + " | " if asr_flag_reason else "") + "transcript barely resembles the reference"
    if coverage < MIN_COVERAGE:
        quality_warnings.append(
            f"The recording contains only {coverage*100:.0f}% as many syllables as the reference -- "
            f"the recitation may be incomplete or partly missed by the recogniser.")
    if coverage > 2.0:
        quality_warnings.append("The transcript is much longer than the reference -- possible noise or ASR hallucination.")
    if uncertain_frac > 0.5:
        quality_warnings.append("Most flagged errors fall on words the recogniser was unsure about -- "
                                "they may be recognition mistakes rather than mispronunciations.")

    if not score_valid or asr_flagged:
        reliability = "low"
    elif coverage < 0.7 or uncertain_frac > 0.5 or (mean_prob is not None and mean_prob < 0.6):
        reliability = "medium"
    else:
        reliability = "high"
    stages["quality"] = {"match_ratio": match_ratio, "coverage": coverage, "score_valid": score_valid,
                         "mean_word_probability": mean_prob, "uncertain_error_fraction": round(uncertain_frac, 3),
                         "reliability": reliability, "warnings": quality_warnings}

    # ---- Stage 6: rubrics ----
    r1 = R1.evaluate(alignment)
    r2 = R2.evaluate(alignment, guru_aksharas)
    r3 = R3.evaluate(guru_aksharas, learner_aksharas, alignment)
    stages["rubric1"] = {"score": r1.score, "errors": r1.errors,
                         "aspiration_errors": r1.aspiration_errors, "conjunct_errors": r1.conjunct_errors,
                         "dvitva_errors": r1.dvitva_errors, "vowel_length_errors": r1.vowel_length_errors,
                         "vowel_errors": r1.vowel_errors, "visarga_errors": r1.visarga_errors,
                         "other_substitutions": r1.other_substitutions,
                         "missing": r1.missing, "extra": r1.extra}
    stages["rubric2"] = {"score": r2.score, "errors": r2.errors,
                         "total_anunasika_aksharas": r2.total_anunasika_aksharas,
                         "total_plain_nasals": r2.total_plain_nasals,
                         "total_weight": r2.total_weight, "penalty": r2.penalty}
    stages["rubric3"] = {"score": r3.score, "boundary_errors": r3.boundary_errors,
                         "guru_word_count": r3.guru_word_count, "learner_word_count": r3.learner_word_count}

    # ---- Stage 7: scoring ----
    report = build_report(sample_id, r1, r2, r3, weights=weights)
    report_dict = report.to_dict()
    report_dict.update({
        "guru_text": guru_text_norm, "learner_text": learner_text_final, "script": guru_script,
        "used_transliteration_fallback": used_transliteration_fallback,
        "asr_flagged": asr_flagged, "asr_flag_reason": asr_flag_reason,
        "timing_available": timing_result["timing_available"],
        "timed_errors": timed,
        "score_valid": score_valid, "quality_warnings": quality_warnings,
        "reliability": reliability, "match_ratio": match_ratio, "coverage": coverage,
        "practice_points": practice_points(alignment),
        "alignment_preview": alignment_preview,
    })
    if asr_flagged:
        print(f"[warning] {sample_id}: {asr_flag_reason}. Score may be unreliable.")
    stages["scoring"] = {"overall_score": report_dict["overall_score"], "grade": report_dict["grade"]}
    report_dict["stages"] = stages
    return report_dict