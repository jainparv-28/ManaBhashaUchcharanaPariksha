#!/usr/bin/env python3
"""
web/app.py
----------
Small Flask backend for a browser frontend on top of the EXISTING pipeline.
Nothing under src/ or scripts/ is modified by this feature -- this file
only calls evaluate_sample(), exactly like scripts/run_pariksha.py already
does, and hands the JSON (including report['timed_errors']) to the browser.

Run:
    pip install -r web/requirements-web.txt
    # (openai-whisper must also be installed -- see main README)
    python web/app.py
Then open http://127.0.0.1:5000 in a browser.

Endpoints
---------
GET  /                                serves web/static/index.html
GET  /uploads/<session_id>/<file>     serves back the audio the user just
                                       uploaded, so the browser can play it
                                       and draw its waveform
POST /api/evaluate                    multipart form:
                                         guru_text (str) OR guru_text_file
                                         learner_audio (file, required)
                                         guru_audio (file, optional -- just
                                           for side-by-side listening)
                                         lang ("sa" | "te", default "sa")
                                       -> JSON report incl. timed_errors
"""
from __future__ import annotations
from src.asr.base import ASRResult
from dotenv import load_dotenv
import os
import sys
import uuid
import shutil
import mimetypes
import subprocess
import traceback
import tempfile
from flask import Flask, request, jsonify, send_from_directory
from openai import OpenAI
load_dotenv()

# Python's mimetypes module doesn't know about .weba (WebM audio) out of
# the box, so send_from_directory falls back to application/octet-stream --
# many browsers then refuse to play it in an <audio> element even though
# the bytes are perfectly valid. Register it explicitly.
mimetypes.add_type("audio/webm", ".weba")
mimetypes.add_type("audio/webm", ".webm")

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, REPO_ROOT)

from src.pipeline import evaluate_sample  # noqa: E402

UPLOAD_ROOT = os.path.join(tempfile.gettempdir(), "uploads")
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(UPLOAD_ROOT, exist_ok=True)

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="")

_whisper_asr = None  # lazy singleton -- loading Whisper's weights is slow
_FFMPEG = shutil.which("ffmpeg")
if not _FFMPEG:
    print("[warning] ffmpeg not found on PATH -- .weba/.webm recordings will be served "
          "as-is for browser playback, which Safari (and some other browsers) cannot "
          "decode. Install ffmpeg (same requirement Whisper already has) to fix this.")

class _GroqWhisperWrapper:
    def __init__(self):
        self.client = OpenAI(
            api_key=os.environ.get("GROQ_API_KEY"),
            base_url="https://api.groq.com/openai/v1"
        )

    def transcribe(self, audio_path: str, lang: str = "sa", **kwargs):
        with open(audio_path, "rb") as f:
            res = self.client.audio.transcriptions.create(
                model="whisper-large-v3-turbo",
                file=f,
                language=lang,
                response_format="verbose_json"
            )
        data = res if isinstance(res, dict) else res.model_dump()
        return ASRResult(
            text=data.get("text", "").strip(),
            language=data.get("language", lang),
            duration=data.get("duration", 0.0),
            words=data.get("words") or [],
            segments=data.get("segments", []),
            avg_logprob=0.0,
            no_speech_prob=0.0,
            prompt_echo_suspected=False,
            diagnostics={"backend": "groq_whisper"}
        )
def _get_asr_backend():
    global _whisper_asr
    if _whisper_asr is None:
        _whisper_asr = _GroqWhisperWrapper()
    return _whisper_asr


def _make_browser_wav(src_path: str) -> str | None:
    """Transcode src_path (e.g. a .weba WebM/Opus recording) to a plain
    16-bit PCM .wav next to it, so the BROWSER can always play it and
    decode it for the waveform -- WebM audio plays fine in Chrome/Firefox
    but Safari can't decode it at all, and some browsers are picky about
    the exact Content-Type. The ORIGINAL file (untouched) is still what
    gets passed to Whisper for scoring -- this only affects playback.
    Returns the wav path, or None if ffmpeg isn't available (caller then
    falls back to serving the original file with its corrected mimetype)."""
    if not _FFMPEG:
        return None
    wav_path = os.path.splitext(src_path)[0] + "_playback.wav"
    try:
        subprocess.run(
            [_FFMPEG, "-y", "-i", src_path, "-ar", "44100", "-ac", "1", wav_path],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60,
        )
        return wav_path
    except Exception as e:
        print(f"[warning] ffmpeg transcoding for browser playback failed for {src_path}: {e}")
        return None


@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")


@app.route("/uploads/<session_id>/<path:filename>")
def serve_upload(session_id, filename):
    directory = os.path.join(UPLOAD_ROOT, session_id)
    mimetype, _ = mimetypes.guess_type(filename)
    return send_from_directory(directory, filename, mimetype=mimetype)


@app.route("/api/evaluate", methods=["POST"])
def api_evaluate():
    try:
        guru_text = (request.form.get("guru_text") or "").strip()
        lang = request.form.get("lang", "sa")
        if lang not in ("sa", "te"):
            lang = "sa"

        if not guru_text:
            guru_text_file = request.files.get("guru_text_file")
            if guru_text_file and guru_text_file.filename:
                guru_text = guru_text_file.read().decode("utf-8").strip()
        if not guru_text:
            return jsonify({"error": "Provide the correct/reference text (guru_text)."}), 400

        learner_file = request.files.get("learner_audio")
        if not learner_file or learner_file.filename == "":
            return jsonify({"error": "Provide the learner's audio file."}), 400

        guru_file = request.files.get("guru_audio")

        session_id = uuid.uuid4().hex
        session_dir = os.path.join(UPLOAD_ROOT, session_id)
        os.makedirs(session_dir, exist_ok=True)

        learner_ext = os.path.splitext(learner_file.filename)[1] or ".weba"
        learner_filename = f"learner{learner_ext}"
        learner_path = os.path.join(session_dir, learner_filename)
        learner_file.save(learner_path)
        # Serve a transcoded .wav to the browser for guaranteed playback/
        # waveform decoding (Safari can't decode WebM/.weba at all); the
        # ORIGINAL file at learner_path -- untouched -- is what's passed to
        # Whisper below, so ASR/scoring behavior is unaffected.
        learner_playback_path = _make_browser_wav(learner_path)
        learner_audio_url = (
            f"/uploads/{session_id}/{os.path.basename(learner_playback_path)}"
            if learner_playback_path else f"/uploads/{session_id}/{learner_filename}"
        )

        guru_audio_url = None
        if guru_file and guru_file.filename:
            guru_ext = os.path.splitext(guru_file.filename)[1] or ".mp3"
            guru_filename = f"guru{guru_ext}"
            guru_path = os.path.join(session_dir, guru_filename)
            guru_file.save(guru_path)
            guru_playback_path = _make_browser_wav(guru_path)
            guru_audio_url = (
                f"/uploads/{session_id}/{os.path.basename(guru_playback_path)}"
                if guru_playback_path else f"/uploads/{session_id}/{guru_filename}"
            )

        asr = _get_asr_backend()
        report = evaluate_sample(
            sample_id=session_id,
            guru_text=guru_text,
            learner_audio_path=learner_path,
            asr=asr,
            asr_lang=lang,
        )

        return jsonify({
            "sample_id": session_id,
            "overall_score": report["overall_score"],
            "grade": report["grade"],
            "guru_text": report["guru_text"],
            "learner_text": report["learner_text"],
            "used_transliteration_fallback": report["used_transliteration_fallback"],
            "asr_flagged": report["asr_flagged"],
            "asr_flag_reason": report["asr_flag_reason"],
            "timing_available": report["timing_available"],
            "timed_errors": report["timed_errors"],
            "rubric1": {"score": report["rubric1"]["score"], "feedback": report["rubric1"]["feedback"]},
            "rubric2": {"score": report["rubric2"]["score"], "feedback": report["rubric2"]["feedback"]},
            "rubric3": {"score": report["rubric3"]["score"], "feedback": report["rubric3"]["feedback"]},
            "tune_note": report["tune_note"],
            "learner_audio_url": learner_audio_url,
            "guru_audio_url": guru_audio_url,
            "duration": report["stages"]["asr"]["duration"],
            "browser_playback_transcoded": bool(_FFMPEG),
        })

    except ValueError as e:
        # Expected, user-actionable problems (e.g. recording too short/empty,
        # missing text) -- not a server bug, so 400 rather than 500.
        return jsonify({"error": str(e)}), 400
    except RuntimeError as e:
        # Whisper failed even after our retry -- still the user's audio's
        # fault most of the time (corrupted/silent file), so treat as 400.
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)