#!/usr/bin/env python3
"""
web/app.py
----------
Flask backend for Uchcharana Pariksha.

Features
--------
* Single fixed admin login (ADMIN_USERNAME / ADMIN_PASSWORD env vars).
  Every page, audio file and API endpoint is blocked until logged in.
* Guru audios + reference texts are stored INSIDE the project
  (audios_for_pronunciation_test/audios_teachers + data/reference_texts) and
  exposed through a dropdown -- nothing about the guru is uploaded by the user.
* The learner's audio is recorded live in the browser and POSTed to
  /api/evaluate together with the selected item id; the response is the same
  report JSON the original version returned.
"""
from __future__ import annotations

import os
import re
import sys
import json
import time
import uuid
import hmac
import shutil
import hashlib
import mimetypes
import subprocess
import traceback
import tempfile
from datetime import timedelta

from flask import (Flask, request, jsonify, send_from_directory, session,
                   redirect, render_template_string)

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

mimetypes.add_type("audio/webm", ".weba")
mimetypes.add_type("audio/webm", ".webm")

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)
from src.asr.base import ASRResult  # noqa: E402
from src.pipeline import evaluate_sample  # noqa: E402

# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------
_candidate_dirs = [
    os.path.join(REPO_ROOT, "web", "static"),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "static"),
    "/var/task/web/static",
]
REF_DIR = os.path.join(REPO_ROOT, "data", "reference_texts")
TEACHER_DIR = os.path.join(REPO_ROOT, "audios_for_pronunciation_test", "audios_teachers")
UPLOAD_ROOT = os.path.join(tempfile.gettempdir(), "uploads")
os.makedirs(UPLOAD_ROOT, exist_ok=True)

# --------------------------------------------------------------------------
# App + single fixed admin credential
# --------------------------------------------------------------------------
app = Flask(__name__, static_folder=None)

ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin@123")
if "ADMIN_PASSWORD" not in os.environ:
    print("[SECURITY WARNING] ADMIN_PASSWORD is not set -- using the insecure default. "
          "Set ADMIN_USERNAME / ADMIN_PASSWORD (and SECRET_KEY) in .env or Vercel env vars.")

# Stateless signed-cookie sessions work on serverless too, as long as every
# instance uses the SAME secret -- so derive one from the credentials if
# SECRET_KEY isn't given explicitly.
app.secret_key = os.environ.get("SECRET_KEY") or hashlib.sha256(
    f"uchcharana|{ADMIN_USERNAME}|{ADMIN_PASSWORD}".encode()).hexdigest()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.environ.get("VERCEL")),
    PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
)

LOGIN_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Admin login -- Uchcharana Pariksha</title>
<style>
  body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
       background:#0f1115;color:#e8e9ec;font-family:-apple-system,"Segoe UI",Roboto,
       "Noto Sans Devanagari","Noto Sans Telugu",sans-serif}
  .card{background:#171a21;border:1px solid #2a2f3a;border-radius:10px;padding:28px 30px;width:340px}
  h1{margin:0 0 4px;font-size:1.4rem} p{margin:0 0 18px;color:#9aa0ac;font-size:.9rem}
  label{display:block;font-size:.85rem;color:#9aa0ac;margin:12px 0 4px}
  input{width:100%;box-sizing:border-box;background:#0f1115;border:1px solid #2a2f3a;color:#e8e9ec;
        border-radius:6px;padding:9px 10px;font-size:1rem}
  button{margin-top:18px;width:100%;background:#f4a300;color:#1a1300;border:none;border-radius:6px;
         padding:10px;font-weight:600;font-size:1rem;cursor:pointer}
  .err{margin-top:14px;color:#e63946;font-size:.9rem}
</style></head><body>
<form class="card" method="post" action="/login">
  <h1>उच्चारण परीक्षा</h1><p>Admin sign-in required</p>
  <label for="username">Username</label>
  <input id="username" name="username" autocomplete="username" required autofocus>
  <label for="password">Password</label>
  <input id="password" name="password" type="password" autocomplete="current-password" required>
  <button type="submit">Log in</button>
  {% if error %}<div class="err">{{ error }}</div>{% endif %}
</form></body></html>"""


@app.before_request
def require_login():
    """Everything except /login needs the admin session."""
    if request.endpoint == "login" or session.get("is_admin"):
        return None
    if request.path.startswith("/api/") and request.path != "/api/index.py":
        return jsonify({"error": "Authentication required"}), 401
    return redirect("/login")


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        u = request.form.get("username", "")
        p = request.form.get("password", "")
        ok_user = hmac.compare_digest(u.encode(), ADMIN_USERNAME.encode())
        ok_pass = hmac.compare_digest(p.encode(), ADMIN_PASSWORD.encode())
        if ok_user and ok_pass:
            session.clear()
            session["is_admin"] = True
            session.permanent = True
            return redirect("/")
        time.sleep(0.7)  # slow down password guessing
        error = "Invalid username or password."
    elif session.get("is_admin"):
        return redirect("/")
    return render_template_string(LOGIN_HTML, error=error), (401 if error else 200)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect("/login")


# --------------------------------------------------------------------------
# Guru items (reference text + internally stored audio)
# --------------------------------------------------------------------------
def _item_sort_key(item_id: str):
    m = re.match(r"([a-z]+)(\d+)$", item_id)
    return (0 if item_id.startswith("shlok") else 1, int(m.group(2)) if m else 0, item_id)


def _teacher_audio_filename(item_id: str, meta: dict):
    # 1) any audio filename listed in metadata.json for this item
    for v in meta.values():
        if isinstance(v, str) and v.lower().endswith((".mp3", ".wav", ".m4a", ".ogg")):
            fn = os.path.basename(v)
            if os.path.isfile(os.path.join(TEACHER_DIR, fn)):
                return fn
    # 2) naming convention: shlokamN -> sanskrit_shlokaN.mp3, padyamN -> telugu_padyamN.mp3
    m = re.match(r"(shlokam|padyam)(\d+)$", item_id)
    if m:
        prefix = "sanskrit_shloka" if m.group(1) == "shlokam" else "telugu_padyam"
        fn = f"{prefix}{m.group(2)}.mp3"
        if os.path.isfile(os.path.join(TEACHER_DIR, fn)):
            return fn
    return None


def _load_items() -> dict:
    with open(os.path.join(REF_DIR, "metadata.json"), "r", encoding="utf-8") as f:
        metadata = json.load(f)
    items = {}
    for item_id in sorted(metadata.keys(), key=_item_sort_key):
        meta = metadata[item_id]
        text_path = os.path.join(REF_DIR, f"{item_id}_unicode.txt")
        if not os.path.isfile(text_path):
            continue
        with open(text_path, "r", encoding="utf-8") as f:
            text = f.read().strip()
        m = re.match(r"([a-z]+)(\d+)$", item_id)
        kind = "Shlokam" if item_id.startswith("shlok") else "Padyam"
        label = f"{kind} {m.group(2)}" if m else item_id
        language = meta.get("language", "")
        audio_fn = _teacher_audio_filename(item_id, meta)
        items[item_id] = {
            "id": item_id,
            "label": f"{label} ({language})" if language else label,
            "language": language,
            "lang": meta.get("whisper_lang", "sa"),
            "text": text,
            "audio_file": audio_fn,
            "audio_url": f"/guru-audio/{item_id}" if audio_fn else None,
        }
    return items


@app.route("/api/items")
def api_items():
    items = _load_items()
    public = [{k: v for k, v in it.items() if k != "audio_file"} for it in items.values()]
    return jsonify({"items": public})


@app.route("/guru-audio/<item_id>")
def guru_audio(item_id):
    item = _load_items().get(item_id)
    if not item or not item["audio_file"]:
        return "Not Found", 404
    mimetype = mimetypes.guess_type(item["audio_file"])[0] or "audio/mpeg"
    return send_from_directory(TEACHER_DIR, item["audio_file"], mimetype=mimetype, conditional=True)


# --------------------------------------------------------------------------
# ASR backend (unchanged)
# --------------------------------------------------------------------------
_whisper_asr = None
_FFMPEG = shutil.which("ffmpeg")
if not _FFMPEG:
    print("[warning] ffmpeg not found on PATH -- recordings will be served as-is for "
          "browser playback (fine for Chrome/Firefox; Safari may not play .webm).")


class _GroqWhisperWrapper:
    def __init__(self):
        if OpenAI is None:
            raise RuntimeError("openai is not installed")
        api_key = os.environ.get("GROQ_API_KEY", "").strip().strip('"').strip("'")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY environment variable is missing.")
        self.client = OpenAI(api_key=api_key, base_url="https://api.groq.com/openai/v1", timeout=45.0)

    def transcribe(self, audio_path: str, lang: str = "sa", **kwargs):
        ext = os.path.splitext(audio_path)[1].lower()
        filename = "audio.webm" if ext in (".weba", "") else f"audio{ext}"
        with open(audio_path, "rb") as f:
            res = self.client.audio.transcriptions.create(
                model="whisper-large-v3-turbo",
                file=(filename, f),
                language=lang,
                response_format="verbose_json",
            )
        data = res if isinstance(res, dict) else res.model_dump()
        return ASRResult(
            text=data.get("text", "").strip(),
            duration=data.get("duration", 0.0),
            words=data.get("words") or [],
            avg_logprob=0.0,
            no_speech_prob=0.0,
            prompt_echo_suspected=False,
            diagnostics={"backend": "groq_whisper", "language": data.get("language", lang),
                         "segments": data.get("segments", [])},
        )


def _get_asr_backend():
    global _whisper_asr
    if _whisper_asr is None:
        _whisper_asr = _GroqWhisperWrapper()
    return _whisper_asr


def _make_browser_wav(src_path: str):
    if not _FFMPEG:
        return None
    wav_path = os.path.splitext(src_path)[0] + "_playback.wav"
    try:
        subprocess.run([_FFMPEG, "-y", "-i", src_path, "-ar", "44100", "-ac", "1", wav_path],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
        return wav_path
    except Exception as e:
        print(f"[warning] ffmpeg transcoding failed for {src_path}: {e}")
        return None


# --------------------------------------------------------------------------
# Static pages
# --------------------------------------------------------------------------
def _find_static_file(filename: str):
    for directory in _candidate_dirs:
        if os.path.isfile(os.path.join(directory, filename)):
            return directory, filename
    return None, None


@app.route("/")
@app.route("/api")
@app.route("/api/index.py")
def index():
    directory, filename = _find_static_file("index.html")
    if directory:
        return send_from_directory(directory, filename, mimetype="text/html")
    return "index.html not found", 404


@app.route("/uploads/<session_id>/<path:filename>")
def serve_upload(session_id, filename):
    directory = os.path.join(UPLOAD_ROOT, session_id)
    mimetype, _ = mimetypes.guess_type(filename)
    return send_from_directory(directory, filename, mimetype=mimetype)


# --------------------------------------------------------------------------
# Evaluate
# --------------------------------------------------------------------------
_ALLOWED_AUDIO_EXT = {".webm", ".weba", ".ogg", ".m4a", ".mp4", ".wav", ".mp3"}


@app.route("/api/evaluate", methods=["POST"])
def api_evaluate():
    try:
        item_id = (request.form.get("item_id") or "").strip()
        item = _load_items().get(item_id)
        if not item:
            return jsonify({"error": "Select a valid shloka / padyam first."}), 400

        learner_file = request.files.get("learner_audio")
        if not learner_file or learner_file.filename == "":
            return jsonify({"error": "No learner recording received. Please record first."}), 400

        session_id = uuid.uuid4().hex
        session_dir = os.path.join(UPLOAD_ROOT, session_id)
        os.makedirs(session_dir, exist_ok=True)

        learner_ext = os.path.splitext(learner_file.filename)[1].lower()
        if learner_ext not in _ALLOWED_AUDIO_EXT:
            learner_ext = ".webm"
        learner_filename = f"learner{learner_ext}"
        learner_path = os.path.join(session_dir, learner_filename)
        learner_file.save(learner_path)
        if os.path.getsize(learner_path) == 0:
            return jsonify({"error": "The recording is empty. Please record again."}), 400

        learner_playback_path = _make_browser_wav(learner_path)
        learner_audio_url = (
            f"/uploads/{session_id}/{os.path.basename(learner_playback_path)}"
            if learner_playback_path else f"/uploads/{session_id}/{learner_filename}"
        )

        report = evaluate_sample(
            sample_id=f"{item_id}__{session_id}",
            guru_text=item["text"],
            learner_audio_path=learner_path,
            asr=_get_asr_backend(),
            asr_lang=item["lang"],
        )

        return jsonify({
            "sample_id": session_id,
            "item_id": item_id,
            "item_label": item["label"],
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
            "guru_audio_url": item["audio_url"],
            "duration": report["stages"]["asr"]["duration"],
            "browser_playback_transcoded": True,
        })

    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


CONTENT_TYPES = {
    ".css": "text/css", ".js": "application/javascript", ".html": "text/html",
    ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon",
}


@app.route("/<path:filename>")
def serve_static(filename):
    filename = filename.lstrip("/")
    directory, target_file = _find_static_file(filename)
    if directory:
        ext = os.path.splitext(filename)[1].lower()
        mimetype = CONTENT_TYPES.get(ext, mimetypes.guess_type(filename)[0] or "application/octet-stream")
        return send_from_directory(directory, target_file, mimetype=mimetype)
    return "Not Found", 404


if __name__ == "__main__":
    app.run(debug=True, port=5000)