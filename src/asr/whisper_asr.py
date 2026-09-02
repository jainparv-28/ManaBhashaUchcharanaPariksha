"""
whisper_asr.py
--------------
Default, easy-to-install ASR backend using OpenAI Whisper.

MODIFIED: this backend now logs, at load time and at every transcribe()
call, concrete evidence that real audio decoding actually happened --
model size loaded, the exact audio_path and language handed to
whisper.transcribe(), and (from Whisper's own result dict) the detected
language and number of decoded segments with timestamps. A backend that
was faking transcription (e.g. returning a canned string) could not
produce per-segment timestamps that vary with the actual audio -- so
printing them is a concrete way to confirm the audio itself was decoded,
not just that some text came back.
"""

from __future__ import annotations
from .base import ASRBackend


class WhisperASR(ASRBackend):
    def __init__(self, model_size: str = "small", verbose: bool = False):
        try:
            import whisper  # noqa: F401
        except ImportError as e:
            raise ImportError(
                "openai-whisper is not installed. Run: pip install openai-whisper "
                "--break-system-packages   (older pip versions: drop the flag, or use a venv)"
            ) from e
        import whisper
        self._whisper = whisper
        self.model_size = model_size
        self.verbose = verbose
        if verbose:
            print(f"[WhisperASR] loading model '{model_size}' ...")
        self.model = whisper.load_model(model_size)
        if verbose:
            n_params = sum(p.numel() for p in self.model.parameters())
            print(f"[WhisperASR] model '{model_size}' loaded ({n_params:,} params)")

    def transcribe(self, audio_path: str, lang: str = "sa", initial_prompt: str = None) -> str:
        kwargs = {"language": lang, "verbose": False}
        if initial_prompt:
            kwargs["initial_prompt"] = initial_prompt[:400]

        result = self.model.transcribe(audio_path, **kwargs)

        if self.verbose:
            segments = result.get("segments", [])
            detected_lang = result.get("language")
            print(f"[WhisperASR] decoded {audio_path}")
            print(f"    requested lang={lang!r}, whisper-detected lang={detected_lang!r}")
            if segments:
                print(f"    {len(segments)} segment(s), audio duration ~{segments[-1]['end']:.1f}s")
            else:
                print("    0 segments returned (silence, non-speech, or empty audio?)")
            for seg in segments[:3]:
                print(f"    [{seg['start']:.1f}s-{seg['end']:.1f}s] {seg['text'][:60]!r}")
            if len(segments) > 3:
                print(f"    ... ({len(segments) - 3} more segment(s))")

        return result["text"].strip()
