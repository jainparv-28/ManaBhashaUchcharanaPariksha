from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ASRResult:
    """Rich ASR result. Backends return this instead of a bare string so the
    pipeline can tell a genuinely clean recitation apart from a transcript
    that was never really 'heard' -- e.g. Whisper echoing its initial_prompt
    back verbatim on quiet/unclear audio instead of transcribing it."""
    text: str
    avg_logprob: Optional[float] = None      # higher (closer to 0) = more confident
    no_speech_prob: Optional[float] = None   # higher = backend thinks there's no speech here
    prompt_echo_suspected: bool = False
    diagnostics: dict = field(default_factory=dict)


class ASRBackend(ABC):
    @abstractmethod
    def transcribe(self, audio_path: str, lang: str = "sa", initial_prompt: str = None) -> ASRResult:
        """Return an ASRResult for the audio at audio_path.

        IMPORTANT: `initial_prompt`, when supported, should be used only to
        bias the decoder toward the expected SCRIPT/vocabulary register --
        never pass the exact reference text of the item being scored as the
        literal prompt. Whisper (and similar seq2seq ASR) can lock onto a
        strong prompt and reproduce it verbatim regardless of what the
        audio actually contains, especially on quiet, noisy, or short
        recordings -- this silently turns every learner's score into 100%
        regardless of real pronunciation. See whisper_asr.py for the
        concrete mitigation used here."""
        raise NotImplementedError


class NullASR(ASRBackend):
    """Placeholder backend used in tests / demos where audio isn't available
    and a ready-made transcript is supplied directly instead."""

    def transcribe(self, audio_path: str, lang: str = "sa", initial_prompt: str = None) -> ASRResult:
        raise RuntimeError(
            "NullASR cannot transcribe audio. Configure a real ASR backend "
            "(see src/asr/whisper_asr.py or README.md 'ASR backends'), or "
            "call the pipeline in --text-only mode with a pre-made transcript."
        )