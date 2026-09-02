"""
pipeline.py
-----------
End-to-end Uchcharana Pariksha:

  guru_text  ----------------------------\
                                           >--> akshara segmentation --> phonetic
  learner_audio --[ASR backend]--> text --/     alignment --> rubric 1/2/3 --> report

MODIFIED: every stage of the pipeline now goes through a StageLog
(src/stagelog.py). Pass verbose=True to print each stage live; either way,
the full trace is embedded in the returned report dict as
report["pipeline_trace"], so a saved JSON report is itself an audit trail
of exactly what happened -- in particular, whether learner_text came from
a real ASR call on real audio (and how long that took, how many bytes the
audio file was, what Whisper's decoder actually returned) versus being
supplied directly as pre-made text.

New report fields (beyond what existed before):
  - learner_text_source: "asr" | "provided_text"
  - asr_backend: class name of the ASR backend used, or None
  - asr_audio_path / asr_audio_bytes / asr_elapsed_seconds: only set when
    learner_text_source == "asr"
  - pipeline_trace: list of {stage, t+, detail, ...} dicts, in order
"""

from __future__ import annotations
from typing import Optional
import unicodedata

from src.phonetics.akshara import segment_aksharas
from src.phonetics.scripts import detect_script
from src.phonetics.transliteration import ensure_native_script
from src.alignment.align import align_aksharas
from src.rubrics import rubric1_syllable_pronunciation as R1
from src.rubrics import rubric2_anunasika as R2
from src.rubrics import rubric3_word_splitting as R3
from src.scoring import build_report
from src.asr.base import ASRBackend, NullASR
from src.stagelog import StageLog


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFC", text.strip())


def evaluate_sample(sample_id: str, guru_text: str, learner_text: Optional[str] = None,
                     learner_audio_path: Optional[str] = None,
                     asr: Optional[ASRBackend] = None, weights: Optional[dict] = None,
                     asr_lang: str = "sa", verbose: bool = False):
    """Run the full pipeline for one sample. See module docstring for the
    new logging/audit behaviour. All original arguments and return shape
    are unchanged (report is still a dict); only new keys were added."""
    log = StageLog(sample_id, verbose=verbose)
    log.stage("start", f"sample_id={sample_id}",
              mode="text-only" if learner_text is not None else "audio+asr")

    used_transliteration_fallback = False
    learner_text_source = "provided_text"
    asr_backend_name = None
    asr_audio_bytes = None
    asr_elapsed_seconds = None

    # ---- Stage: guru text (always known up front) -------------------------
    log.stage("guru_text_received",
              guru_text[:60] + ("..." if len(guru_text) > 60 else ""),
              data={"guru_text": guru_text, "sample_id": sample_id,
                    "mode": "text-only" if learner_text is not None else "audio+asr"},
              length=len(guru_text))

    # ---- Stage: obtain learner text (ASR or provided) ----------------------
    if learner_text is None:
        if learner_audio_path is None:
            log.warn("neither learner_text nor learner_audio_path was provided")
            raise ValueError("Provide either learner_text or learner_audio_path")

        backend = asr or NullASR()
        asr_backend_name = type(backend).__name__
        log.stage("asr_dispatch",
                  f"sending {learner_audio_path} to {asr_backend_name} (lang={asr_lang})",
                  audio_path=learner_audio_path, lang=asr_lang, backend=asr_backend_name)

        if isinstance(backend, NullASR):
            # NullASR always raises -- surfaced explicitly rather than being
            # a silent stack trace with no context about which sample failed.
            log.warn(f"{sample_id}: no real ASR backend configured (NullASR) -- "
                     f"cannot transcribe {learner_audio_path}. Pass --asr whisper "
                     f"or supply learner_text/--demo-text-dir instead.")

        import time
        t0 = time.time()
        # transcribe_checked() runs a preflight (file exists / non-empty /
        # not a placeholder) BEFORE calling the backend, and logs the real
        # elapsed decode time + a preview of what came back.
        learner_text = backend.transcribe_checked(
            learner_audio_path, lang=asr_lang, initial_prompt=guru_text, stagelog=log,
        )
        asr_elapsed_seconds = round(time.time() - t0, 3)
        import os
        asr_audio_bytes = os.path.getsize(learner_audio_path)
        learner_text_source = "asr"
    else:
        log.stage("learner_text_provided_directly",
                  learner_text[:60] + ("..." if len(learner_text) > 60 else ""),
                  data={"learner_text": learner_text, "source": "provided_text"},
                  length=len(learner_text))

    # ---- Stage: normalize ---------------------------------------------------
    guru_text_n = _normalize(guru_text)
    learner_text_n = _normalize(learner_text)
    log.stage("normalize", "NFC-normalized + stripped both texts",
              data={"guru_text_before": guru_text, "guru_text_after": guru_text_n,
                    "learner_text_before": learner_text, "learner_text_after": learner_text_n},
              guru_len=len(guru_text_n), learner_len=len(learner_text_n))

    # ---- Stage: script detection --------------------------------------------
    guru_script = detect_script(guru_text_n)
    log.stage("script_detect", f"guru_script={guru_script}",
              data={"guru_script": guru_script, "guru_text": guru_text_n})
    if guru_script == "unknown":
        log.warn(f"could not detect a supported script in guru_text for '{sample_id}'")
        raise ValueError(
            f"Could not detect a supported script (Devanagari or Telugu) in guru_text "
            f"for sample '{sample_id}': {guru_text_n!r}"
        )

    # ---- Stage: romanization safety net -------------------------------------
    pre_fallback_text = learner_text_n
    learner_text_n, used_transliteration_fallback = ensure_native_script(learner_text_n, guru_script)
    if used_transliteration_fallback:
        log.warn(
            f"learner_text came back ROMANIZED (no Devanagari/Telugu chars) -- "
            f"auto-transliterated IAST->{guru_script}. Treat this report as "
            f"lower-confidence.",
            data={"romanized_text": pre_fallback_text, "transliterated_text": learner_text_n,
                  "target_script": guru_script},
            romanized_text_preview=pre_fallback_text[:60],
            transliterated_preview=learner_text_n[:60],
        )
    else:
        log.stage("script_fallback_check",
                   "learner_text already in native script, no fallback needed",
                   data={"used_transliteration_fallback": False})

    # ---- Stage: akshara segmentation ----------------------------------------
    def _akshara_to_dict(a):
        return {"text": a.text, "consonants": a.consonants, "vowel_sign": a.vowel_sign,
                "is_independent_vowel": a.is_independent_vowel, "anusvara": a.anusvara,
                "candrabindu": a.candrabindu, "visarga": a.visarga, "script": a.script}

    guru_aksharas = segment_aksharas(guru_text_n, script=guru_script)
    learner_aksharas = segment_aksharas(learner_text_n, script=guru_script)

    # Two separate stage entries (not one combined one) so write_stage_files()
    # produces two separate JSON files -- guru's segmented aksharas and the
    # learner's segmented aksharas each get their own file, easy to diff
    # side-by-side or feed independently into something else.
    log.stage("segmentation_guru_aksharas",
              f"guru text segmented into {len(guru_aksharas)} aksharas",
              data={"script": guru_script, "source_text": guru_text_n,
                    "akshara_count": len(guru_aksharas),
                    "aksharas": [_akshara_to_dict(a) for a in guru_aksharas]},
              akshara_count=len(guru_aksharas),
              preview=[a.text for a in guru_aksharas[:8]])

    log.stage("segmentation_learner_aksharas",
              f"learner text segmented into {len(learner_aksharas)} aksharas",
              data={"script": guru_script, "source_text": learner_text_n,
                    "akshara_count": len(learner_aksharas),
                    "aksharas": [_akshara_to_dict(a) for a in learner_aksharas]},
              akshara_count=len(learner_aksharas),
              preview=[a.text for a in learner_aksharas[:8]])

    # ---- Stage: alignment ----------------------------------------------------
    alignment = align_aksharas(guru_aksharas, learner_aksharas)
    tag_counts = {}
    for p in alignment:
        tag_counts[p.tag] = tag_counts.get(p.tag, 0) + 1
    alignment_full = [
        {"guru": p.guru.text if p.guru else None, "learner": p.learner.text if p.learner else None,
         "tag": p.tag, "cost": p.cost, "note": p.note}
        for p in alignment
    ]
    log.stage("alignment", f"{len(alignment)} aligned pairs",
              data={"alignment": alignment_full, "tag_counts": tag_counts},
              tag_counts=tag_counts)

    # ---- Stage: rubrics --------------------------------------------------------
    r1 = R1.evaluate(alignment)
    log.stage("rubric1", f"score={r1.score}",
              data={"score": r1.score, "total_aksharas": r1.total_aksharas,
                    "aspiration_errors": r1.aspiration_errors, "conjunct_errors": r1.conjunct_errors,
                    "dvitva_errors": r1.dvitva_errors, "other_substitutions": r1.other_substitutions,
                    "errors": r1.errors, "feedback": r1.feedback()},
              aspiration_errors=r1.aspiration_errors, conjunct_errors=r1.conjunct_errors,
              dvitva_errors=r1.dvitva_errors, other_substitutions=r1.other_substitutions)

    r2 = R2.evaluate(alignment, guru_aksharas)
    log.stage("rubric2", f"score={r2.score}",
              data={"score": r2.score, "total_anunasika_aksharas": r2.total_anunasika_aksharas,
                    "errors": r2.errors, "feedback": r2.feedback()},
              errors=len(r2.errors), total_anunasika_aksharas=r2.total_anunasika_aksharas)

    r3 = R3.evaluate(guru_aksharas, learner_aksharas)
    log.stage("rubric3", f"score={r3.score}",
              data={"score": r3.score, "guru_word_count": r3.guru_word_count,
                    "learner_word_count": r3.learner_word_count,
                    "boundary_errors": r3.boundary_errors, "feedback": r3.feedback()},
              guru_word_count=r3.guru_word_count, learner_word_count=r3.learner_word_count)

    # ---- Stage: build report -----------------------------------------------
    report = build_report(sample_id, r1, r2, r3, weights=weights)
    report_dict = report.to_dict()
    report_dict["guru_text"] = guru_text_n
    report_dict["learner_text"] = learner_text_n
    report_dict["script"] = guru_script
    report_dict["used_transliteration_fallback"] = used_transliteration_fallback

    # New audit fields -- this is the part that lets you PROVE, from the
    # saved JSON report alone, whether a given learner's score came from
    # real ASR on real audio.
    report_dict["learner_text_source"] = learner_text_source
    report_dict["asr_backend"] = asr_backend_name
    report_dict["asr_audio_path"] = learner_audio_path if learner_text_source == "asr" else None
    report_dict["asr_audio_bytes"] = asr_audio_bytes
    report_dict["asr_elapsed_seconds"] = asr_elapsed_seconds

    if used_transliteration_fallback:
        print(f"[warning] {sample_id}: ASR output was romanized, not native script -- "
              f"transliterated automatically. Treat this report as lower-confidence and "
              f"consider a bigger Whisper model (see RUNNING.md troubleshooting).")

    report_dict["alignment_preview"] = [
        {"guru": p.guru.text if p.guru else "-", "learner": p.learner.text if p.learner else "-", "tag": p.tag}
        for p in alignment
    ]

    # Shallow-copy BEFORE attaching pipeline_trace to report_dict, so the
    # "done" stage's snapshot doesn't end up holding a circular reference
    # to the trace it's itself a part of (which would break JSON dumping).
    log.stage("done", f"overall_score={report_dict['overall_score']} grade={report_dict['grade']}",
              data={"final_report": dict(report_dict)})
    report_dict["pipeline_trace"] = log.trace
    return report_dict