"""
timing.py
---------
Maps each pronunciation error found by align.py back to a TIME INTERVAL in
the learner's audio, using the ASR backend's word-level timestamps (see
ASRResult.words in src/asr/base.py).

How the mapping works
----------------------
Whisper (and most ASR backends) only gives timestamps per WORD, not per
akshara/character. So:
  1. The learner's akshara stream is grouped into words the same way
     rubric 3 does (phonetics.akshara.word_index_map / to_words).
  2. If the ASR backend returned the same number of words as our own
     word-grouping found, word i's timestamp is used directly for every
     akshara in word i (the common, best case).
  3. If the counts don't match (ASR sometimes merges/splits words
     differently than pure whitespace-splitting), we fall back to
     distributing the total audio duration evenly across our word count,
     and mark every interval `"approximate": true` so this is never
     silently presented as more precise than it is.
  4. A "missing" error (guru akshara never pronounced) has no learner
     audio to point to -- we report the GAP between the nearest learner
     words before/after it instead, so a reviewer knows roughly where in
     the audio the omission happened.
  5. If no word-level timing is available at all (text-only mode, or the
     ASR backend didn't supply `words`), every interval is `None` and
     `timing_available` is False -- errors are still fully detected, just
     without a timestamp.
"""

from __future__ import annotations
from typing import List, Optional

from ..phonetics.akshara import word_index_map, to_words
from .align import AlignedPair


def _word_intervals(learner_aksharas, asr_words: Optional[list], duration: Optional[float]):
    """Return (intervals, approximate) where intervals[i] = (start, end)
    for word index i of learner_aksharas' whitespace-grouped words."""
    n_words = len(to_words(learner_aksharas))
    if n_words == 0:
        return [], False

    if asr_words and len(asr_words) == n_words:
        return [(w["start"], w["end"]) for w in asr_words], False

    if asr_words and duration is None:
        duration = asr_words[-1]["end"]

    if duration is not None and duration > 0:
        # Even split across the audio -- best effort when word counts
        # don't line up (e.g. ASR merged two words, or split a conjunct).
        step = duration / n_words
        return [(round(i * step, 3), round((i + 1) * step, 3)) for i in range(n_words)], True

    return [(None, None)] * n_words, True


def map_errors_to_time(alignment: List[AlignedPair], learner_aksharas, guru_aksharas,
                        asr_words: Optional[list] = None, duration: Optional[float] = None) -> dict:
    """Return {"timing_available": bool, "approximate": bool, "errors": [...]}.

    Each entry in "errors" (for every non-match AlignedPair) looks like:
        {
          "type": "aspiration_error" | "anunasika_error" | "dvitva_error" |
                   "conjunct_error" | "substitution" | "missing" | "extra",
          "guru_akshara": str|None,
          "learner_akshara": str|None,
          "note": str,
          "start": float|None,   # seconds into the learner's audio
          "end": float|None,
          "approximate": bool,   # True if word counts didn't line up 1:1
        }
    """
    timing_available = bool(asr_words) or duration is not None
    l_word_idx = word_index_map(learner_aksharas)
    intervals, approx_flag = _word_intervals(learner_aksharas, asr_words, duration)

    def interval_for_learner_akshara(a) -> tuple:
        wi = l_word_idx.get(id(a))
        if wi is None or wi >= len(intervals):
            return (None, None)
        return intervals[wi]

    # Precompute, in alignment order, the running list of (start,end) for
    # every pair that DOES have a learner-side interval -- used to find the
    # nearest neighbours around a "missing" (guru-only) error to report a
    # gap instead of nothing.
    results = []
    ordered_known = []  # (position_in_alignment, start, end)
    for pos, p in enumerate(alignment):
        if p.tag == "match" or p.cost == 0:
            continue
        if p.learner is not None:
            start, end = interval_for_learner_akshara(p.learner)
        else:
            start, end = (None, None)
        results.append({
            "type": p.tag,
            "guru_akshara": p.guru.text if p.guru else None,
            "learner_akshara": p.learner.text if p.learner else None,
            "note": p.note,
            "start": start,
            "end": end,
            "approximate": approx_flag if start is not None else None,
        })

    # Fill in "missing" errors' interval as the gap between the previous
    # and next timed neighbours in the alignment sequence.
    timed_positions = [i for i, r in enumerate(results) if r["start"] is not None]
    for i, r in enumerate(results):
        if r["type"] != "missing" or r["start"] is not None:
            continue
        prev_end = None
        next_start = None
        for j in range(i - 1, -1, -1):
            if results[j]["end"] is not None:
                prev_end = results[j]["end"]
                break
        for j in range(i + 1, len(results)):
            if results[j]["start"] is not None:
                next_start = results[j]["start"]
                break
        r["start"] = prev_end
        r["end"] = next_start
        r["approximate"] = True
        if prev_end is None and next_start is None:
            r["note"] = (r["note"] or "") + " (no timing available)"
        else:
            r["note"] = (r["note"] or "") + " -- akshara was skipped; interval is the gap " \
                         "between the surrounding learner audio, not a precise timestamp"

    return {
        "timing_available": timing_available,
        "approximate": approx_flag,
        "errors": results,
    }