# Uchcharana Pariksha (उच्चारण परीक्षा) — Mana Bhasha Pronunciation Test

An automated pronunciation-assessment engine that compares each **learner's**
recitation against the **guru's** reference text, scored against the three
rubrics from Pavan's email, and built to work directly against the real
Mana Bhasha dataset: **5 Sanskrit shlokas (Devanagari) + 6 Telugu padyams
(Telugu script)**, each with many learner responses.

1. **Syllable perfection** — alpaprana vs mahaprana (त/थ, త/థ), sanyukta
   akshara / conjuncts (द्व्य vs ध्व्य), dvitva akshara / gemination
   (द्ध vs द्द).
2. **Anunasika (nasalisation)** — e.g. गङ्गा mis-said as गम्गा / गन्गा.
3. **Word splitting (pada-cheda)** — did the learner segment the
   recitation into the same words as the guru.

Tune/intonation is **deliberately not scored**, per the guru's guidance —
shown only as an optional appreciative note.

**Two scripts, one engine.** The phonetic core (`src/phonetics/`) is
script-generic: Devanagari and Telugu share the same underlying
Sanskrit-derived phonology (5×5 varga grid of consonants), so one
`ScriptProfile` per script (see `src/phonetics/scripts.py`) is all that's
needed to drive segmentation, feature extraction, and error classification
for both the Sanskrit shlokas and the Telugu padyams. The script is
auto-detected from the guru's reference text — no per-item configuration
needed beyond the language code for ASR.

**Full pipeline observability (new).** Every run can be traced stage by
stage — from guru text, through the ASR call on learner audio, through
akshara segmentation, phonetic alignment, and all three rubrics, to the
final score — either printed live to the terminal (`--verbose`) or written
out as individual JSON files per stage (`--write-stages`), so you can
audit exactly what happened for any sample after the fact. See
"Observability: verbose mode, stage JSON files, and the ASR audit" below.

---

## The actual dataset

```
audios_for_pronunciation_test/
├── audios_teachers/
│   ├── sanskrit_shloka1.mp3 ... sanskrit_shloka5.mp3
│   └── telugu_padyam1.mp3 ... telugu_padyam6.mp3
├── audios_learners/
│   ├── shlokam1_responses/<uuid>.weba   (7–11 learner recordings per item)
│   ├── shlokam2_responses/ ... shlokam5_responses/
│   ├── padyam1_responses/  ... padyam6_responses/
└── audios_text/
    └── audios_text.docx    (source of the guru reference texts)
```

`audios_text.docx` has already been transcribed into individual
`data/reference_texts/<item>_unicode.txt` (+ `_roman.txt`) files in this
repo, one per item (`shlokam1`..`shlokam5`, `padyam1`..`padyam6`), plus
`data/reference_texts/metadata.json` recording each item's script,
Whisper language code, and its teacher/learner audio folder names. **The
guru's own audio is not needed for scoring** — the ground-truth text is
already known from the docx, so only the *learner's* audio needs
transcribing.

## Why comparison happens in the *text layer*

```
guru reference text (already known, from audios_text.docx)  ─────────────┐
                                                                            ├──▶ akshara segmentation ──▶ phonetically-
learner .weba/.mp3 audio ──[ASR backend, per-item language]──▶ learner text┘      weighted alignment ──▶ 3 rubrics ──▶ report
```

Text-layer comparison is dependency-light, fully auditable, and lets the
phonetic engine be validated with **zero audio and zero internet access**
(see "Network limitations" below) — the comparison logic doesn't care
whether the text came from a human transcript or an ASR model. Audio-layer
(phoneme/forced-alignment) comparison is discussed as a follow-on in
`REPORT.md`.

## File structure

```
mana_bhasha_uchcharana_pariksha/
├── README.md                  <- you are here
├── REPORT.md                  <- design write-up, results, limitations, next steps
├── requirements.txt
├── config.yaml                 <- rubric weights, paths, ASR backend choice
├── audios_for_pronunciation_test/   <- PLACE YOUR REAL DATASET HERE (see below)
│   ├── audios_teachers/*.mp3
│   ├── audios_learners/<item>_responses/*.weba
│   └── audios_text/audios_text.docx
├── data/
│   ├── reference_texts/        <- guru texts, already extracted from the docx
│   │   ├── shlokam1_unicode.txt / shlokam1_roman.txt   (x5, Devanagari)
│   │   ├── padyam1_unicode.txt / padyam1_roman.txt     (x6, Telugu)
│   │   └── metadata.json       <- item -> {language, script, whisper_lang, audio filenames}
│   └── demo_learner_texts/     <- synthetic learner transcripts for demoing
│       ├── shlokam1/*.txt          without needing real audio (see below)
│       └── padyam2/*.txt
├── src/
│   ├── asr/
│   │   ├── base.py              <- ASRBackend interface + audio preflight check (new)
│   │   └── whisper_asr.py       <- Whisper default backend, with verbose decode logging (new)
│   ├── phonetics/
│   │   ├── scripts.py           <- Devanagari + Telugu Unicode/phonetic profiles
│   │   ├── akshara.py           <- script-generic syllable segmentation
│   │   └── features.py          <- aspiration / anunasika / conjunct / gemination features
│   ├── alignment/
│   │   └── align.py             <- phonetically-weighted akshara alignment
│   ├── rubrics/
│   │   ├── rubric1_syllable_pronunciation.py
│   │   ├── rubric2_anunasika.py
│   │   └── rubric3_word_splitting.py
│   ├── scoring.py               <- combines rubrics into overall report
│   ├── stagelog.py              <- stage-by-stage trace utility (new)
│   ├── pipeline.py              <- end-to-end orchestration (auto-detects script; now fully traced)
│   └── report_generator.py      <- JSON + Markdown report writer, + per-stage JSON writer (new)
├── scripts/
│   ├── run_pariksha.py          <- CLI for one learner x one item (now supports --verbose / --write-stages)
│   └── batch_evaluate.py        <- CLI for the whole dataset (now supports --verbose / --write-stages / ASR audit)
├── tests/                       <- unit + pipeline tests, incl. Telugu coverage (all passing)
└── outputs/reports/             <- generated reports (+ optional per-stage JSON) land here (gitignored in practice)
```

## Quick start

```bash
pip install -r requirements.txt

# 1. Run the unit tests (validates the phonetic engine against Pavan's own
#    examples, in BOTH Devanagari and Telugu — no audio or internet needed)
python tests/test_akshara.py
python tests/test_features.py
python tests/test_alignment.py
python tests/test_pipeline.py

# 2. Run the bundled demo (real shlokam1 + padyam2 text, synthetic learner
#    errors, no audio needed — see "About the demo" below)
python scripts/batch_evaluate.py --items shlokam1 padyam2 \
    --demo-text-dir data/demo_learner_texts --out-dir outputs/reports
cat outputs/reports/shlokam1/demo_aspiration_error.md
cat outputs/reports/overall_summary.csv
```

Single learner, single item, text-only mode (fastest way to sanity-check a rubric):

```bash
python scripts/run_pariksha.py \
  --sample-id shlokam1_check \
  --guru-text-file data/reference_texts/shlokam1_unicode.txt \
  --learner-text "अस्त्युत्तरस्यां दिशि थेवतात्मा हिमालयो नाम नगाधिराजः ।"
```

## Running on the real dataset

1. Copy/symlink your real `audios_for_pronunciation_test/` folder (with
   `audios_learners/`, `audios_teachers/`, `audios_text/`) into the repo
   root, matching the layout above exactly (it already does — this repo's
   folder names were taken directly from your `ls -R` output).
2. Install an ASR backend + `ffmpeg` (needed to decode `.weba`/`.mp3`):

   ```bash
   sudo apt-get install ffmpeg      # or your OS's equivalent
   pip install openai-whisper --break-system-packages
   ```
3. **Before running the full batch**, check that your real `.weba` files
   aren't accidentally empty or truncated (this repo's own demo folders
   contain intentional 0-byte placeholders — see "About the demo" — and
   the new preflight check will refuse anything under ~2KB rather than
   silently transcribing garbage):

   ```bash
   find audios_for_pronunciation_test/audios_learners -name "*.weba" -size -2k
   ```

   If this returns nothing, your files are fine. If it lists files, those
   specific recordings need to be re-recorded/re-uploaded before they can
   be scored — the pipeline will now skip them cleanly and report them in
   the ASR audit summary instead of producing a bogus result.

4. Run the whole dataset:

   ```bash
   python scripts/batch_evaluate.py --asr whisper --out-dir outputs/reports
   ```

   Or just one or two items first, to sanity-check before committing to a
   full (bilingual, ~100-file) Whisper run:

   ```bash
   python scripts/batch_evaluate.py --asr whisper --items shlokam1 \
       --limit-per-item 2 --out-dir outputs/reports
   ```

This produces, per learner: `outputs/reports/<item>/<learner_uuid>.json`
(for LMS integration) and `.md` (human-readable); per item:
`outputs/reports/<item>/_item_summary.csv`; and across everything:
`outputs/reports/overall_summary.csv` — one row per learner response, so a
guru/teacher can sort by score to see who needs the most help, per item or
overall.

---

## Observability: verbose mode, stage JSON files, and the ASR audit

The pipeline (`src/pipeline.py`) now runs every sample through a
`StageLog` (`src/stagelog.py`) that records each step — guru text
received, ASR dispatch + preflight + transcription, text normalization,
script detection, romanization-fallback check, akshara segmentation,
phonetic alignment, and each of the 3 rubrics — with the **full**
underlying data (every akshara, the entire alignment, every rubric error),
not just a preview. This is always captured; `--verbose` and
`--write-stages` are two different ways to *see* it.

### `--verbose` — print every stage live to the terminal

```bash
python scripts/run_pariksha.py \
  --sample-id shlokam1_check \
  --guru-text-file data/reference_texts/shlokam1_unicode.txt \
  --learner-text "अस्त्युत्तरस्यां दिशि थेवतात्मा हिमालयो नाम नगाधिराजः ।" \
  --verbose
```

```bash
python scripts/batch_evaluate.py --asr whisper --items shlokam1 \
  --limit-per-item 2 --verbose
```

Use this while debugging a single sample or watching a small batch run —
it prints elapsed time per stage, ASR decode timing, akshara counts,
alignment tag counts, and each rubric's score as they happen.

### `--write-stages` — write one JSON file per pipeline stage

```bash
python scripts/run_pariksha.py \
  --sample-id shlokam1_check \
  --guru-text-file data/reference_texts/shlokam1_unicode.txt \
  --learner-text "अस्त्युत्तरस्यां दिशि थेवतात्मा हिमालयो नाम नगाधिराजः ।" \
  --write-stages
```

writes, alongside the usual `outputs/reports/shlokam1_check.json` / `.md`:

```
outputs/reports/shlokam1_check_stages/
  00_all_stages.json              <- every stage, one file
  01_start.json
  02_guru_text_received.json
  03_learner_text_provided_directly.json   (or 03_asr_dispatch.json / 04_asr_preflight.json /
                                              05_asr_transcribe_complete.json in audio mode)
  0N_normalize.json
  0N_script_detect.json
  0N_script_fallback_check.json
  0N_segmentation_guru_aksharas.json     <- every akshara of the guru's text, full fields
  0N_segmentation_learner_aksharas.json  <- every akshara of the learner's text, full fields
  0N_alignment.json               <- every aligned pair, tag, cost, note
  0N_rubric1.json                 <- full error list + feedback
  0N_rubric2.json
  0N_rubric3.json
  0N_done.json                    <- final report snapshot
```

For a batch run, add `--write-stages` to `batch_evaluate.py` the same way;
it writes `outputs/reports/<item>/<learner_id>_stages/` per learner. This
is **off by default** in batch mode since it multiplies file count by
~12–15x per learner (fine for a handful of samples, noisy for the full
~100-file dataset — turn it on only for the samples you want to inspect
closely, e.g. with `--items shlokam1 --limit-per-item 2`).

### ASR audit summary (batch_evaluate.py, on by default)

After any `batch_evaluate.py` run, a summary block answers, at a glance,
whether learner audio was **actually** transcribed:

```
========================================================================
ASR AUDIT SUMMARY
========================================================================
  scored: 9
  preflight_rejected: 1

  Scored via REAL ASR on audio : 9
  Scored via demo-text override: 0
  Rejected by preflight (empty/too-small audio): 1

  Real ASR calls: avg decode time 3.42s, avg transcript length 61 chars.
  (Non-trivial, varying decode times + non-empty transcripts of plausible
   length are the evidence that audio was genuinely decoded, not stubbed.)

  Files rejected by the audio preflight check (< 2000 bytes or missing) --
  these produced NO score at all, so they won't silently show up as a
  suspiciously perfect/empty result:
    - shlokam1/some_uuid  (0 bytes)
========================================================================
```

Disable with `--no-audit-asr` if you don't want it.

### Audio preflight check (`src/asr/base.py`)

Any audio file under ~2KB (or missing) is now refused with an explicit
`AudioPreflightError` **before** it's sent to the ASR backend, instead of
silently producing an empty/garbage transcript that would otherwise look
like a normal (if bad) score. This specifically catches the 0-byte
placeholder `.weba` files this repo ships for the two demo items (see
"About the demo" below) — running `--asr whisper` on those without
`--demo-text-dir` will now cleanly skip them and say why, rather than
quietly scoring silence.

---

## About the demo (`data/demo_learner_texts/`)

Since this sandbox cannot reach the real `.weba`/`.mp3` audio (see
below), the pipeline is instead demonstrated against the **real reference
texts** with two synthetic learner transcripts per item, standing in for
what a correct/incorrect ASR transcript would look like:

- `shlokam1/demo_perfect.txt` — identical to the guru's Shlokam 1 text (sanity check, expect 100/100)
- `shlokam1/demo_aspiration_error.txt` — पृथिव्या → पृतिव्या (थ→त, a genuine alpaprana/mahaprana minimal pair)
- `padyam2/demo_perfect.txt` — identical to the guru's Padyam 2 text (Telugu)
- `padyam2/demo_geminate_error.txt` — వికార → విఖార (క→ఖ, the Telugu counterpart of त/थ)

Matching empty placeholder `.weba` files live under
`audios_for_pronunciation_test/audios_learners/{shlokam1,padyam2}_responses/`
purely so the batch script's real folder-scanning logic (which lists
`*.weba` files to discover learner IDs) can be exercised end-to-end — swap
in real audio and drop `--demo-text-dir` to use them for real. **These
placeholder files are exactly what the new audio preflight check is
designed to catch** if you accidentally run `--asr whisper` against them
directly.

## ASR backends

`src/asr/base.py` defines a small `ASRBackend` interface
(`transcribe(audio_path, lang) -> text`) plus a `transcribe_checked()`
wrapper that all call sites now use, which runs the preflight check, times
the decode, and logs a preview of the returned text (see "Observability"
above). `data/reference_texts/metadata.json` records the right ASR
language code per item (`"sa"` for the 5 Sanskrit shlokas, `"te"` for the
6 Telugu padyams), and `batch_evaluate.py` always passes it through
automatically (`evaluate_sample(..., asr_lang=meta["whisper_lang"])`) so
Telugu audio is never accidentally transcribed with a Sanskrit language
hint (which would measurably hurt accuracy). `run_pariksha.py` exposes the
same thing as `--lang sa`/`--lang te` for single-sample runs.

| Backend | Notes |
|---|---|
| **Whisper** (`src/asr/whisper_asr.py`, bundled) | Easiest to install (`pip install openai-whisper`). Handles `.weba`/`.mp3` fine via `ffmpeg`. Decent word accuracy in both Sanskrit and Telugu, but its language model tends to "auto-correct" subtle mispronunciations back to canonical spelling — a real risk here, since we *want* to see the mistake, not have it silently fixed. `WhisperASR(verbose=True)` now also prints per-segment timestamps and Whisper's own detected language, so you can see the decoder actually working through the audio, not just returning a string. |
| **Bhashini API** | Government of India's speech API with strong Indic-language (incl. Telugu) coverage; recommended if network access to it is available in your deployment. |
| **IndicWav2Vec2 / phoneme-CTC models** | Best fit long-term (see `REPORT.md` "Audio-layer alternative") since a phoneme-level (not word-level) recognizer is far less prone to auto-correcting aspiration/nasalisation errors away. |

Whichever you choose, implement `ASRBackend.transcribe()` and pass an
instance to `evaluate_sample(..., asr=your_backend)` or
`scripts/run_pariksha.py --asr ...` / `scripts/batch_evaluate.py --asr ...`.

## Network limitations in this environment

This project was built and fully tested in a sandbox whose outbound
network is limited to package registries (pypi, npm, github, etc.) — it
cannot reach the machine where the real dataset lives, nor model-weight
hosts (Hugging Face, OpenAI's model store). That's why:
- the real `.weba`/`.mp3` audio could not be processed here — the folder
  structure above was built from your `ls -R` output and populated with
  empty placeholder files so the *code path* (folder scanning, per-item
  metadata lookup, batch reporting, and now the audio preflight check)
  could still be exercised end-to-end;
- Whisper is provided as code but not exercised on real audio here
  (`pip install` would succeed; the model-weight download on first run
  would not, without network access from wherever you actually run this).
  The new observability features (verbose staged trace, per-stage JSON
  files, ASR audit summary) were instead demonstrated against a
  drop-in fake ASR backend that reads real bytes off disk and returns a
  transcript through the exact same `transcribe_checked()` code path that
  `WhisperASR` uses — so the machinery is proven correct even though the
  actual Whisper model never ran here.

Everything that doesn't require external audio/network — Devanagari *and*
Telugu akshara segmentation, phonetic feature extraction, alignment, all
three rubrics, the full text-layer pipeline (including the real guru
texts for all 11 items), and the new staged-trace/audit machinery — is
implemented, unit-tested, and demonstrated end-to-end in this repo.

## Command reference

| Goal | Command |
|---|---|
| Run all unit tests | `python tests/test_akshara.py && python tests/test_features.py && python tests/test_alignment.py && python tests/test_pipeline.py` |
| Text-only single sample | `python scripts/run_pariksha.py --sample-id ID --guru-text-file FILE --learner-text "..."` |
| Text-only single sample, verbose trace | add `--verbose` to the above |
| Text-only single sample, per-stage JSON files | add `--write-stages` to the above |
| Single sample from real audio | `python scripts/run_pariksha.py --sample-id ID --guru-text-file FILE --learner-audio AUDIO.weba --asr whisper --lang sa` (`--lang te` for Telugu) |
| Same, with verbose trace + stage files | add `--verbose --write-stages` |
| Bundled demo (no audio needed) | `python scripts/batch_evaluate.py --items shlokam1 padyam2 --demo-text-dir data/demo_learner_texts --out-dir outputs/reports` |
| Real dataset, one item, quick sanity check | `python scripts/batch_evaluate.py --asr whisper --items shlokam1 --limit-per-item 2 --out-dir outputs/reports --verbose --write-stages` |
| Real dataset, full batch | `python scripts/batch_evaluate.py --asr whisper --out-dir outputs/reports` |
| Full batch, skip the ASR audit table | add `--no-audit-asr` |
| Check for empty/placeholder audio files before a run | `find audios_for_pronunciation_test/audios_learners -name "*.weba" -size -2k` |