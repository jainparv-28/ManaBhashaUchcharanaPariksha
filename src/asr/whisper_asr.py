"""
whisper_asr.py
--------------
Default ASR backend using OpenAI Whisper (`pip install openai-whisper`).

WHY EVERY LEARNER WAS SCORING 100%
-----------------------------------
The original version of this backend was called with
`initial_prompt=guru_text` -- i.e. it handed Whisper the EXACT answer key
for the item being scored, on every single call. Whisper's decoder treats
`initial_prompt` as strong conditioning text to continue from. On chanted
Sanskrit/Telugu recitation -- often quiet, reverberant, or recorded on a
phone mic -- Whisper (especially the 'small' model) will frequently just
continue/echo the prompt back almost verbatim instead of transcribing what
was actually said, particularly when its own acoustic confidence is low.
The symptom is exactly what was reported: learner_text ends up identical
(or near-identical) to guru_text for every recording, regardless of actual
pronunciation, so every rubric reports zero errors and every score is 100.

THE FIX (two parts, both applied below)
----------------------------------------
1. Never pass the item-specific guru_text as the literal prompt. Instead
   use a small, fixed, GENERIC prompt per script/language that contains
   normal Devanagari/Telugu vocabulary (so the decoder still locks onto the
   right script instead of romanizing -- the original, legitimate reason
   the prompt existed) but contains none of the actual words being tested,
   so there is nothing content-specific for the model to fall back to.
2. Decode with `condition_on_previous_text=False` (stops the prompt-bias
   from re-entrenching itself across internal windows) and surface
   per-segment confidence (`avg_logprob`, `no_speech_prob`) plus an
   explicit `prompt_echo_suspected` flag computed by comparing the
   transcript against the (separately supplied) reference text -- so the
   pipeline can flag/downgrade a suspicious "perfect" transcript instead of
   silently trusting it. See src/pipeline.py for how this flag is used.
"""

from __future__ import annotations
from typing import Optional

from .base import ASRBackend, ASRResult

# Generic, script-appropriate priming text -- NOT the content being graded.
# Chosen to contain a broad spread of consonants/vowels/anusvara so the
# decoder locks onto the right script and register without ever matching
# the specific shloka/padyam under test.
_SCRIPT_HINT_PROMPTS = {
    "sa": "ॐ नमः शिवाय। गुरुभ्यो नमः। हरिः ॐ तत्सत्। शान्तिः शान्तिः शान्तिः॥",
    "te": "ఓం నమః శివాయ। గురుభ్యో నమః। శ్రీ గణేశాయ నమః। శుభమస్తు॥",
}


class WhisperASR(ASRBackend):
    def __init__(self, model_size: str = "small"):
        try:
            import whisper  # noqa: F401
        except ImportError as e:
            raise ImportError(
                "openai-whisper is not installed. Run: pip install openai-whisper "
                "--break-system-packages   (older pip versions: drop the flag, or use a venv)"
            ) from e
        import whisper
        self._whisper = whisper
        self.model = whisper.load_model(model_size)

    def transcribe(self, audio_path: str, lang: str = "sa", initial_prompt: str = None) -> ASRResult:
        # `initial_prompt` may still be passed in by callers for backward
        # compatibility / to signal "this item has a prompt available", but
        # we deliberately IGNORE its literal content and substitute a
        # generic, non-content-specific script hint -- see module docstring.
        prompt = _SCRIPT_HINT_PROMPTS.get(lang)

        # Sanity-check the audio BEFORE handing it to Whisper: an empty,
        # truncated, or extremely short/silent recording (e.g. the browser
        # mic captured almost nothing) is what triggers Whisper's
        # word-timestamp DTW step to crash with "cannot reshape tensor of
        # 0 elements" deep inside torch, which is a confusing 500 error for
        # an end user to see. Fail fast with a clear message instead.
        try:
            samples = self._whisper.audio.load_audio(audio_path)
            duration_s = len(samples) / self._whisper.audio.SAMPLE_RATE
        except Exception as e:
            raise ValueError(f"Could not read audio file '{audio_path}': {e}") from e
        if duration_s < 0.3:
            raise ValueError(
                f"This recording is only {duration_s:.2f}s long -- too short to "
                f"transcribe reliably. Please record at least a few seconds of the "
                f"recitation and try again."
            )

        base_kwargs = {
            "language": lang,
            "condition_on_previous_text": False,
            "temperature": (0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
        }
        if prompt:
            base_kwargs["initial_prompt"] = prompt

        result, had_word_timestamps = self._transcribe_with_fallback(audio_path, base_kwargs)
        text = (result.get("text") or "").strip()

        segments = result.get("segments") or []
        avg_logprob = (sum(s.get("avg_logprob", 0.0) for s in segments) / len(segments)
                        if segments else None)
        no_speech_prob = (sum(s.get("no_speech_prob", 0.0) for s in segments) / len(segments)
                           if segments else None)

        words = []
        for seg in segments:
            for w in seg.get("words", []) or []:
                token = (w.get("word") or "").strip()
                if not token:
                    continue
                words.append({
                    "word": token,
                    "start": round(float(w.get("start", 0.0)), 3),
                    "end": round(float(w.get("end", 0.0)), 3),
                    "probability": w.get("probability"),
                })
        duration = round(float(segments[-1]["end"]), 3) if segments else round(duration_s, 3)

        prompt_echo_suspected = False
        if prompt and text:
            # If Whisper's output is suspiciously close to the *generic
            # priming prompt itself* (rather than to the real guru text,
            # which this backend never saw), that's a second, independent
            # echo signal worth surfacing.
            prompt_echo_suspected = _normalized(text) == _normalized(prompt)

        # Low acoustic confidence (very negative avg_logprob, or high
        # no_speech_prob) combined with a transcript that exists at all is
        # worth flagging too -- the pipeline additionally checks the
        # transcript against the *real* guru_text, which this backend
        # never had access to, for the strongest version of this check.
        low_confidence = (
            (avg_logprob is not None and avg_logprob < -1.0) or
            (no_speech_prob is not None and no_speech_prob > 0.6)
        )

        return ASRResult(
            text=text,
            avg_logprob=avg_logprob,
            no_speech_prob=no_speech_prob,
            prompt_echo_suspected=prompt_echo_suspected or low_confidence,
            diagnostics={
                "model_size": getattr(self.model, "name", None),
                "language": lang,
                "prompt_used": prompt,
                "num_segments": len(segments),
                "low_confidence": low_confidence,
                "word_timestamps_available": had_word_timestamps,
            },
            words=words,
            duration=duration,
        )

    def _transcribe_with_fallback(self, audio_path: str, base_kwargs: dict):
        """Try transcribing WITH word-level timestamps (needed for the
        error-time-interval feature). If Whisper's DTW-based word alignment
        crashes -- a known failure mode on very short/near-silent segments,
        surfacing as "cannot reshape tensor of 0 elements" -- retry once
        without word_timestamps so the user still gets a score, just
        without per-word timing (src/alignment/timing.py already degrades
        gracefully to duration-based estimates when no words are given).
        Returns (result_dict, had_word_timestamps)."""
        try:
            return self.model.transcribe(audio_path, word_timestamps=True, **base_kwargs), True
        except RuntimeError as e:
            msg = str(e)
            if "0 elements" in msg or "reshape tensor" in msg:
                print(f"[warning] Whisper's word-level timestamp alignment failed on "
                      f"'{audio_path}' (likely a very short or near-silent segment) -- "
                      f"retrying without word-level timestamps.")
                try:
                    return self.model.transcribe(audio_path, word_timestamps=False, **base_kwargs), False
                except RuntimeError as e2:
                    raise RuntimeError(
                        "Whisper could not transcribe this audio even without word "
                        "timestamps -- the recording may be corrupted, empty, or entirely "
                        "silent. Please check it and try again."
                    ) from e2
            raise


def _normalized(s: str) -> str:
    return "".join(s.split())