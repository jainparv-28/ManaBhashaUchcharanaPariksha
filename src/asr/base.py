"""
base.py
-------
Pluggable ASR interface. Uchcharana Pariksha needs to turn the LEARNER's
audio into Devanagari/Telugu text so it can be compared against the guru's
reference text.

MODIFIED: added `AudioPreflightError` and `preflight_check()` so that a
0-byte or missing audio file (e.g. this repo's own placeholder .weba files,
see README "About the demo") is caught with an explicit, loud error BEFORE
we ever hand it to an ASR backend -- rather than silently sending an empty
file into whisper.transcribe(), which can return an empty string or garbage
text that would otherwise look like a normal (if bad) transcription.
"""

from __future__ import annotations
import os
from abc import ABC, abstractmethod

# Below this size, treat the file as "not real audio" (this repo's demo
# placeholder .weba files are 0 bytes; real short recitations are typically
# tens to hundreds of KB even compressed). Adjust if your real recordings
# are legitimately very short.
MIN_PLAUSIBLE_AUDIO_BYTES = 2000


class AudioPreflightError(RuntimeError):
    """Raised when an audio file looks unusable (missing / empty / too
    small to plausibly contain real speech) -- BEFORE any ASR call."""
    pass


def preflight_check(audio_path: str) -> int:
    """Returns the file size in bytes if the file looks usable, else raises
    AudioPreflightError. This is called automatically by every ASRBackend
    subclass's `transcribe()` wrapper (see `ASRBackend.transcribe_checked`)."""
    if not os.path.isfile(audio_path):
        raise AudioPreflightError(f"Audio file does not exist: {audio_path}")
    size = os.path.getsize(audio_path)
    if size == 0:
        raise AudioPreflightError(
            f"Audio file is EMPTY (0 bytes): {audio_path} -- this looks like "
            f"a placeholder file, not a real recording. Nothing was transcribed."
        )
    if size < MIN_PLAUSIBLE_AUDIO_BYTES:
        raise AudioPreflightError(
            f"Audio file is suspiciously small ({size} bytes): {audio_path} -- "
            f"almost certainly not a real recitation recording. Refusing to "
            f"send it to ASR. If this is legitimately valid, raise "
            f"MIN_PLAUSIBLE_AUDIO_BYTES in src/asr/base.py."
        )
    return size


class ASRBackend(ABC):
    @abstractmethod
    def transcribe(self, audio_path: str, lang: str = "sa", initial_prompt: str = None) -> str:
        """Return a transcript of the audio at audio_path."""
        raise NotImplementedError

    def transcribe_checked(self, audio_path: str, lang: str = "sa",
                            initial_prompt: str = None, stagelog=None) -> str:
        """Wrapper that ALWAYS runs preflight_check() first, and (if a
        StageLog is passed) records every step -- file size, elapsed
        transcription time, and a preview of the returned text -- so a
        report/log can prove audio really was converted to text and isn't
        just an empty string that happened not to crash anything."""
        import time

        size = preflight_check(audio_path)
        if stagelog:
            stagelog.stage(
                "asr_preflight", f"audio file OK: {audio_path}",
                data={"audio_path": audio_path, "file_size_bytes": size, "lang": lang,
                      "backend": type(self).__name__, "initial_prompt": initial_prompt},
                file_size_bytes=size, lang=lang, backend=type(self).__name__,
            )

        t0 = time.time()
        text = self.transcribe(audio_path, lang=lang, initial_prompt=initial_prompt)
        elapsed = round(time.time() - t0, 3)

        if stagelog:
            stagelog.stage(
                "asr_transcribe_complete",
                f"backend={type(self).__name__} produced {len(text)} chars in {elapsed}s",
                data={"audio_path": audio_path, "backend": type(self).__name__,
                      "lang": lang, "elapsed_seconds": elapsed,
                      "audio_file_size_bytes": size,
                      "transcribed_text": text, "transcribed_text_len": len(text)},
                elapsed_seconds=elapsed,
                text_preview=(text[:60] + "...") if len(text) > 60 else text,
                text_len=len(text),
            )
        if not text.strip():
            msg = (f"ASR backend {type(self).__name__} returned an EMPTY transcript for "
                   f"{audio_path} (file size {size} bytes, {elapsed}s inference) -- the "
                   f"audio was sent to ASR but nothing came back. This report should be "
                   f"treated as unscored / needs manual review, not a genuine zero-error result.")
            if stagelog:
                stagelog.warn(msg, data={"audio_path": audio_path, "file_size_bytes": size})
            else:
                print(f"[warning] {msg}")
        return text


class NullASR(ASRBackend):
    """Placeholder backend used in tests / demos where audio isn't available
    and a ready-made transcript is supplied directly instead."""

    def transcribe(self, audio_path: str, lang: str = "sa", initial_prompt: str = None) -> str:
        raise RuntimeError(
            "NullASR cannot transcribe audio. Configure a real ASR backend "
            "(see src/asr/whisper_asr.py or README.md 'ASR backends'), or "
            "call the pipeline in --text-only mode with a pre-made transcript."
        )
