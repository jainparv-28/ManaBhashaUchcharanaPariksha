# Uchcharana Pariksha -- Web UI

A small browser frontend on top of the existing pipeline (`src/pipeline.py`).
Nothing under `src/` or `scripts/` was changed to add this -- `web/app.py`
just calls `evaluate_sample()`, exactly like `scripts/run_pariksha.py`
already does, and returns `report["timed_errors"]` as JSON for the browser
to draw.

## What it does

1. You type/paste the correct reference text (or upload a `.txt`), pick
   Sanskrit or Telugu, and upload the learner's audio (and optionally the
   guru's audio, just for side-by-side listening).
2. The backend runs the real pipeline (ASR -> normalization -> akshara
   segmentation -> alignment -> rubrics -> error-to-time mapping).
3. The browser decodes the learner's audio client-side and draws its
   waveform on a `<canvas>`, with a colored band over every pronunciation
   error at its exact (start, end) time interval -- aspiration errors in
   red, anunasika in orange, dvitva in purple, conjunct in blue, generic
   substitutions in gray, extra sounds in teal, and omitted (missing)
   aksharas as a dark band over the audio gap where they should have been.
4. Hover a band for the guru-vs-learner akshara and the note; click it (or
   a row in the error table below) to seek the audio there and play it.

## Setup

```bash
# from the repo root
pip install -r web/requirements-web.txt
pip install openai-whisper --break-system-packages   # if not already installed
python web/app.py
```

Then open **http://127.0.0.1:5000** in a browser.

The first evaluation will be slow (Whisper's model weights load once into
memory and are then reused for every subsequent request in the same server
process).

## Notes / limitations

- Uploaded audio is saved to `web/uploads/<session_id>/` so the browser can
  play it back and draw its waveform; nothing is deleted automatically --
  clear that folder periodically if you're running this somewhere shared.
- If the browser can't decode the uploaded audio codec (rare, but some
  `.weba` variants), the waveform falls back to a flat line while playback,
  seeking, and the error table (with timestamps) still work normally.
- This is a local dev server (`app.run(debug=True)`) meant for the guru/LMS
  team to try things out, not a production deployment -- put it behind a
  real WSGI server (gunicorn, etc.) and add auth before exposing it beyond
  localhost.