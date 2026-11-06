"""
timing.py -- maps each error to a time interval in the learner's audio.

ASR gives word timestamps only. Each learner akshara is placed inside its
word's interval in proportion to its position in the text, so errors get
akshara-level (interpolated) intervals. Omissions take the gap between the
nearest timed neighbours, always clamped to a valid, non-inverted span.
"""
from __future__ import annotations
from typing import List, Optional

from ..phonetics.akshara import to_words
from .align import AlignedPair

MIN_SPAN = 0.15          # seconds; minimum width shown for a gap/omission
UNCERTAIN_PROB = 0.5     # ASR word probability below this => uncertain error


def _timeline(asr_words, duration):
    words = []
    for w in asr_words or []:
        try:
            s, e = float(w["start"]), float(w["end"])
        except (KeyError, TypeError, ValueError):
            continue
        ln = max(len(str(w.get("word", "")).strip()), 1)
        p = w.get("probability")
        words.append((ln, s, max(e, s), p if isinstance(p, (int, float)) else None))
    if not words and duration and duration > 0:
        words.append((1, 0.0, float(duration), None))
    tl, c = [], 0
    for ln, s, e, p in words:
        tl.append((c, c + ln, s, e, p))
        c += ln
    return tl, c


def _pos_to_time(tl, pos, is_end):
    for c0, c1, s, e, p in tl:
        if (pos <= c1) if is_end else (pos < c1):
            frac = min(max((pos - c0) / max(c1 - c0, 1e-9), 0.0), 1.0)
            return s + frac * (e - s), p
    c0, c1, s, e, p = tl[-1]
    return e, p


def _akshara_times(learner_aksharas, tl, total_asr):
    """{id(akshara): (start, end, prob)} for every non-space learner akshara."""
    core = [a for a in learner_aksharas if not a.text.isspace()]
    total_l = sum(len(a.text) for a in core)
    out = {}
    if not tl or total_l == 0:
        return out
    scale = total_asr / total_l
    c = 0
    for a in core:
        a0, a1 = c * scale, (c + len(a.text)) * scale
        c += len(a.text)
        t0, _ = _pos_to_time(tl, a0, False)
        t1, _ = _pos_to_time(tl, a1, True)
        _, prob = _pos_to_time(tl, (a0 + a1) / 2, False)
        out[id(a)] = (round(t0, 3), round(max(t1, t0), 3), prob)
    return out


def _clamp_gap(start, end, duration):
    if start is None and end is None:
        return None, None
    if start is None:
        start = end
    if end is None:
        end = start
    if start > end:                       # neighbours out of order -> shared boundary
        start = end = (start + end) / 2
    if end - start < MIN_SPAN:            # zero/near-zero gap -> small visible span
        mid = (start + end) / 2
        start, end = max(0.0, mid - MIN_SPAN / 2), mid + MIN_SPAN / 2
        if duration:
            end = min(end, float(duration))
            start = min(start, end)
    return round(start, 3), round(end, 3)


def map_errors_to_time(alignment: List[AlignedPair], learner_aksharas, guru_aksharas,
                       asr_words: Optional[list] = None, duration: Optional[float] = None) -> dict:
    tl, total_asr = _timeline(asr_words, duration)
    timing_available = bool(tl)
    n_learner_words = len(to_words(learner_aksharas))
    approx = (not asr_words) or len(asr_words) != n_learner_words
    times = _akshara_times(learner_aksharas, tl, total_asr)
    end_of_audio = tl[-1][3] if tl else duration

    def learner_time(pair):
        if pair.learner is None or pair.learner.text.isspace():
            return None
        return times.get(id(pair.learner))

    results = []
    for idx, p in enumerate(alignment):
        if p.tag == "match" or p.cost == 0:
            continue
        t = learner_time(p)
        start = end = prob = None
        is_approx = None
        if t:
            start, end, prob = t
            is_approx = approx
        elif p.guru is not None and p.learner is None:       # omission -> gap
            prev_end = next_start = None
            for q in reversed(alignment[:idx]):
                qt = learner_time(q)
                if qt:
                    prev_end = qt[1]
                    break
            for q in alignment[idx + 1:]:
                qt = learner_time(q)
                if qt:
                    next_start = qt[0]
                    break
            start, end = _clamp_gap(prev_end, next_start, end_of_audio)
            is_approx = True
            if start is None:
                p_note = (p.note or "") + " (no timing available)"
            else:
                p_note = (p.note or "") + " -- skipped; interval is the gap between surrounding speech"
            results.append(_entry(p, p_note, start, end, is_approx, None))
            continue
        results.append(_entry(p, p.note, start, end, is_approx, prob))

    return {"timing_available": timing_available, "approximate": approx, "errors": results}


def _entry(p, note, start, end, approximate, prob):
    return {
        "type": p.tag,
        "guru_akshara": p.guru.text if p.guru else None,
        "learner_akshara": p.learner.text if p.learner else None,
        "note": note,
        "start": start,
        "end": end,
        "approximate": approximate if start is not None else None,
        "confidence": round(prob, 3) if isinstance(prob, (int, float)) else None,
        "uncertain": bool(isinstance(prob, (int, float)) and prob < UNCERTAIN_PROB),
    }