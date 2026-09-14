"""
pipeline.py
-----------
End-to-end Uchcharana Pariksha:

  guru_text  ----------------------------\
                                           >--> akshara segmentation --> phonetic
  learner_audio --[ASR backend]--> text --/     alignment --> rubric 1/2/3 --> report

Every stage's intermediate output is also captured into `report["stages"]`
(and, via report_generator.write_stages_json, its own JSON file) so each
step of the workflow can be inspected/audited independently:
    1. asr            -- raw ASR transcript + confidence diagnostics
    2. normalization   -- guru/learner text after NFC + whitespace normalize
    3. script_detection-- detected script, transliteration fallback info
    4. segmentation     -- akshara lists for guru and learner
    5. alignment        -- full akshara-by-akshara alignment with tags
    6. rubric1/2/3      -- each rubric's raw result
    7. scoring          -- final weighted report

IMPORTANT SAFETY NET -- ASR "prompt echo": when learner_text comes from a
real ASR backend (not supplied directly as text), and that backend reports
low confidence (via ASRResult.prompt_echo_suspected) while the transcript
still happens to match guru_text closely, the pipeline sets
`report["asr_flagged"] = True` with an explanatory note rather than
silently returning a perfect score. This is what previously caused every
learner to score 100% -- see src/asr/whisper_asr.py for the root cause and
fix in the ASR layer itself; this is the second, independent check at the
pipeline layer.
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
from .asr.base import ASRBackend, ASRResult, NullASR


_WS_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    """NFC-normalize and collapse ANY run of whitespace (space, tab,
    newline) to a single space. This is required so that a guru reference
    text typed with line breaks between padas compares cleanly against
    ASR output, which never produces newlines -- without this, every
    line break in the reference text used to be scored as a phoneme
    substitution/insertion error against the learner. See align.py for a
    second, defence-in-depth fix at the alignment-cost level."""
    text = unicodedata.normalize("NFC", text.strip())
    text = _WS_RE.sub(" ", text)
    return text


def _akshara_preview(aksharas):
    return [
        {
            "text": a.text,
            "consonants": a.consonants,
            "vowel_sign": a.vowel_sign,
            "is_independent_vowel": a.is_independent_vowel,
            "anusvara": a.anusvara,
            "candrabindu": a.candrabindu,
            "visarga": a.visarga,
            "script": a.script,
        }
        for a in aksharas
    ]


def evaluate_sample(sample_id: str, guru_text: str, learner_text: Optional[str] = None,
                     learner_audio_path: Optional[str] = None,
                     asr: Optional[ASRBackend] = None, weights: Optional[dict] = None,
                     asr_lang: str = "sa"):
    """Run the full pipeline for one sample. Returns a dict that always
    contains a `stages` key with every intermediate step's output, in
    addition to the final rubric/overall scoring fields."""
    stages: dict = {}
    used_transliteration_fallback = False
    asr_diagnostics = None
    asr_flagged = False
    asr_flag_reason = None
    asr_words = []
    asr_duration = None

    # ---- Stage 1: ASR (only if learner_text wasn't supplied directly) ----
    if learner_text is None:
        if learner_audio_path is None:
            raise ValueError("Provide either learner_text or learner_audio_path")
        backend = asr or NullASR()
        # NOTE: we intentionally do NOT pass guru_text as the literal ASR
        # prompt -- see src/asr/whisper_asr.py module docstring for why
        # that caused every learner to silently score 100%.
        result = backend.transcribe(learner_audio_path, lang=asr_lang, initial_prompt=guru_text)
        if isinstance(result, ASRResult):
            learner_text = result.text
            asr_diagnostics = result.diagnostics
            asr_diagnostics["avg_logprob"] = result.avg_logprob
            asr_diagnostics["no_speech_prob"] = result.no_speech_prob
            asr_words = result.words or []
            asr_duration = result.duration
            if result.prompt_echo_suspected:
                asr_flagged = True
                asr_flag_reason = "ASR backend reported low confidence / possible prompt echo"
        else:
            # Backward-compat: a backend that still returns a bare string.
            learner_text = result
    stages["asr"] = {
        "mode": "text_supplied" if asr_diagnostics is None and learner_audio_path is None else "audio_transcribed",
        "raw_learner_text": learner_text,
        "diagnostics": asr_diagnostics,
        "words": asr_words,
        "duration": asr_duration,
        "flagged": asr_flagged,
        "flag_reason": asr_flag_reason,
    }

    # ---- Stage 2: normalization ----
    guru_text_norm = _normalize(guru_text)
    learner_text_norm = _normalize(learner_text)
    stages["normalization"] = {
        "guru_text": guru_text_norm,
        "learner_text": learner_text_norm,
    }

    # ---- Stage 3: script detection + transliteration fallback ----
    guru_script = detect_script(guru_text_norm)
    if guru_script == "unknown":
        raise ValueError(
            f"Could not detect a supported script (Devanagari or Telugu) in guru_text "
            f"for sample '{sample_id}': {guru_text_norm!r}"
        )
    learner_text_final, used_transliteration_fallback = ensure_native_script(learner_text_norm, guru_script)
    stages["script_detection"] = {
        "guru_script": guru_script,
        "used_transliteration_fallback": used_transliteration_fallback,
        "learner_text_after_fallback": learner_text_final,
    }

    # Independent sanity check: audio-derived transcript that is IDENTICAL
    # to the guru text combined with any ASR low-confidence signal is
    # exactly the "prompt echo" failure mode -- flag it explicitly here too
    # so it's visible even if a future/alternate ASR backend doesn't set
    # prompt_echo_suspected itself.
    if learner_audio_path is not None and learner_text_final == guru_text_norm and asr_diagnostics:
        if asr_diagnostics.get("low_confidence"):
            asr_flagged = True
            asr_flag_reason = (asr_flag_reason or "") + \
                " | transcript is byte-identical to guru_text with low ASR confidence -- verify against real audio"

    # ---- Stage 4: akshara segmentation ----
    guru_aksharas = segment_aksharas(guru_text_norm, script=guru_script)
    learner_aksharas = segment_aksharas(learner_text_final, script=guru_script)
    stages["segmentation"] = {
        "guru_aksharas": _akshara_preview(guru_aksharas),
        "learner_aksharas": _akshara_preview(learner_aksharas),
    }

    # ---- Stage 5: alignment ----
    alignment = align_aksharas(guru_aksharas, learner_aksharas)
    alignment_preview = [
        {"guru": p.guru.text if p.guru else "-", "learner": p.learner.text if p.learner else "-",
         "tag": p.tag, "cost": p.cost, "note": p.note}
        for p in alignment
    ]
    stages["alignment"] = {"pairs": alignment_preview}

    # ---- Stage 5b: map errors to audio time intervals ----
    timing_result = map_errors_to_time(alignment, learner_aksharas, guru_aksharas,
                                        asr_words=asr_words, duration=asr_duration)
    if used_transliteration_fallback and timing_result["errors"]:
        for e in timing_result["errors"]:
            e["note"] = (e["note"] or "") + " (timing based on word position after " \
                         "romanization fallback -- verify against audio)"
    stages["timing"] = timing_result

    # ---- Stage 6: rubrics ----
    r1 = R1.evaluate(alignment)
    r2 = R2.evaluate(alignment, guru_aksharas)
    r3 = R3.evaluate(guru_aksharas, learner_aksharas)
    stages["rubric1"] = {"score": r1.score, "errors": r1.errors,
                          "aspiration_errors": r1.aspiration_errors,
                          "conjunct_errors": r1.conjunct_errors,
                          "dvitva_errors": r1.dvitva_errors,
                          "other_substitutions": r1.other_substitutions}
    stages["rubric2"] = {"score": r2.score, "errors": r2.errors,
                          "total_anunasika_aksharas": r2.total_anunasika_aksharas}
    stages["rubric3"] = {"score": r3.score, "boundary_errors": r3.boundary_errors,
                          "guru_word_count": r3.guru_word_count,
                          "learner_word_count": r3.learner_word_count}

    # ---- Stage 7: scoring ----
    report = build_report(sample_id, r1, r2, r3, weights=weights)
    report_dict = report.to_dict()
    report_dict["guru_text"] = guru_text_norm
    report_dict["learner_text"] = learner_text_final
    report_dict["script"] = guru_script
    report_dict["used_transliteration_fallback"] = used_transliteration_fallback
    report_dict["asr_flagged"] = asr_flagged
    report_dict["asr_flag_reason"] = asr_flag_reason
    report_dict["timing_available"] = timing_result["timing_available"]
    report_dict["timed_errors"] = timing_result["errors"]
    if used_transliteration_fallback:
        print(f"[warning] {sample_id}: ASR output was romanized, not native script -- "
              f"transliterated automatically. Treat this report as lower-confidence and "
              f"consider a bigger Whisper model (see RUNNING.md troubleshooting).")
    if asr_flagged:
        print(f"[warning] {sample_id}: {asr_flag_reason}. Overall score may be unreliable -- "
              f"please spot-check the audio manually.")
    report_dict["alignment_preview"] = alignment_preview
    stages["scoring"] = {"overall_score": report_dict["overall_score"], "grade": report_dict["grade"]}
    report_dict["stages"] = stages
    return report_dict