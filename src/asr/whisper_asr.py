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

        kwargs = {
            "language": lang,
            "condition_on_previous_text": False,
            "temperature": (0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
        }
        if prompt:
            kwargs["initial_prompt"] = prompt

        result = self.model.transcribe(audio_path, **kwargs)
        text = (result.get("text") or "").strip()

        segments = result.get("segments") or []
        avg_logprob = (sum(s.get("avg_logprob", 0.0) for s in segments) / len(segments)
                        if segments else None)
        no_speech_prob = (sum(s.get("no_speech_prob", 0.0) for s in segments) / len(segments)
                           if segments else None)

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
            },
        )


def _normalized(s: str) -> str:
    return "".join(s.split())