# Report: Uchcharana Pariksha for Mana Bhasha LMS

## 1. Problem statement

Pavan's email asks for a pronunciation test ("uchcharana pariksha") that
compares a learner's recitation of a shloka/padyam against a guru's
reference recitation, graded against three rubrics:

1. Syllable-level pronunciation perfection — alpaprana vs mahaprana
   confusion (त/थ), sanyukta akshara / conjunct errors (द्व्य→ध्व्य,
   ग्भ्य→ग्ब्य), and dvitva akshara / gemination errors (द्ध→द्द,
   distinguishing च्च from च्छ).
2. Anunasika (nasalisation) correctness — e.g. गङ्गा rendered as गम्गा
   or गन्गा.
3. Word splitting (pada-cheda) — matching the guru's segmentation of the
   recitation into words.

Explicitly **out of scope**: tune, intonation, rhythm.

The actual dataset (confirmed via directory listing and the source
`audios_text.docx`) is:

| | Items | Script | Reference audio | Learner responses |
|---|---|---|---|---|
| **Shlokas** | 5 (Sanskrit) | Devanagari | `sanskrit_shloka1..5.mp3` | `shlokam1..5_responses/` — 7 to 11 `.weba` files each |
| **Padyams** | 6 (Telugu) | Telugu | `telugu_padyam1..6.mp3` | `padyam1..6_responses/` — 7 to 10 `.weba` files each |

So this is a **bilingual, many-learners-per-item** dataset (≈100 learner
recordings total across 11 items).

## 2. Approach

### 2.1 Two scripts, one phonetic engine

Telugu padyams are written in **Telugu script**, not Devanagari — a
different Unicode block, different glyphs, but the *same* underlying
Sanskrit-derived phonology (the 5×5 varga grid of velar/palatal/
retroflex/dental/labial stops × alpaprana/mahaprana/voiced/nasal is
identical in structure between the two scripts, e.g. त/थ/द/ध/न in
Devanagari corresponds glyph-for-glyph to త/థ/ద/ధ/న in Telugu).

Rather than writing two parallel phonetic engines, `src/phonetics/scripts.py`
defines a `ScriptProfile` (Unicode ranges for consonants/vowel-signs/
independent-vowels/halant/anusvara/etc., plus the varga table, aspiration
pairs, and homorganic-nasal table) once per script. `akshara.py` and
`features.py` are written entirely against this profile, so segmentation,
aspiration-pair detection, anunasika detection, and gemination/conjunct
detection all work identically for both scripts — the script is
auto-detected from the first script-bearing character in the guru's
reference text (`scripts.detect_script`), so callers never need to specify
it manually.

This was validated directly: `tests/test_alignment.py` includes Telugu
equivalents of every Devanagari test, all passing.

### 2.2 Why akshara-level, not character-level

Devanagari/Telugu text is not phonetically transparent at the raw Unicode
character level — one akshara (orthographic syllable) can span several
code points. A plain string diff would report the wrong error type or
split one perceptual unit across two "characters." The rule-based akshara
segmenter groups halant-joined consonant clusters, trailing vowel signs,
and nasalisation/visarga markers into single akshara units, matching how
a guru would actually count syllables — in either script.

### 2.3 Phonetic feature model, not plain text diff

`src/alignment/align.py` runs a **phonetically-weighted edit distance**
between the guru's and learner's akshara sequences. A substitution that's
*purely* an aspiration flip, *purely* a nasalisation change, or *purely* a
conjunct/gemination change is tagged and costed differently (and more
cheaply) than a generic substitution, so mismatches get the correct rubric
label directly from the alignment backtrace.

### 2.4 Rubric modules

- `rubric1_syllable_pronunciation.py` — aspiration/conjunct/gemination
  error counts, percentage score, actionable per-type feedback.
- `rubric2_anunasika.py` — isolates nasalisation-tagged mismatches, scored
  against the anunasika-akshara count *in the guru's reference*.
- `rubric3_word_splitting.py` — word-level (not akshara-level) comparison
  of guru vs learner segmentation, independent of rubric 1/2.

`src/scoring.py` combines the three (default weights 50/25/25, configurable
in `config.yaml`) into an overall score, grade band, and non-penalising
tune note.

### 2.5 ASR as a pluggable, per-item-language boundary

Guru reference text for all 11 items is **already known** — extracted once
from `audios_text.docx` into `data/reference_texts/<item>_unicode.txt` — so
only the *learner's* `.weba` audio needs transcribing. `src/asr/base.py`
defines a one-method interface; `data/reference_texts/metadata.json` records
the correct ASR language code per item (`"sa"` vs `"te"`), and
`batch_evaluate.py` always forwards it so Telugu audio is never
transcribed with a Sanskrit language hint.

---

## 3. Pipeline observability, audit trail, and the ASR question (new)

The original build asked "does the pipeline work, end to end" and
answered it by running text-only demo samples. A follow-up, entirely fair
question was raised: **is learner audio actually getting converted to
text by the ASR backend, or could that step be silently failing / being
skipped / producing garbage that scores fine anyway?**

Three things were added to answer that with evidence rather than
assertion, none of which change scoring behaviour:

### 3.1 `StageLog` (`src/stagelog.py`) and a fully-traced `pipeline.py`

`evaluate_sample()` now runs every sample through a `StageLog` object that
records, for every stage — guru text received, ASR dispatch, ASR
preflight, ASR transcription complete, text normalization, script
detection, romanization-fallback check, akshara segmentation, phonetic
alignment, and each of the 3 rubrics — the **full** underlying data (every
akshara object, the entire alignment path, every rubric error, the exact
transcript text and decode time returned by the ASR backend), plus a
short, console-friendly summary. This is captured unconditionally;
`verbose=True` additionally prints it live.

Every report dict gained new audit fields:

```
learner_text_source   : "asr" | "provided_text"
asr_backend            : class name of the ASR backend used, or null
asr_audio_path          : path of the audio file that was transcribed
asr_audio_bytes         : size of that file, in bytes
asr_elapsed_seconds    : wall-clock time the ASR call took
pipeline_trace         : the full stage-by-stage trace, as a list
```

A saved report JSON is therefore its own audit log: you can tell, without
re-running anything, whether a given score came from a real ASR call on a
real audio file, how big that file was, and how long decoding took.

### 3.2 Per-stage JSON files (`report_generator.write_stage_files`)

`--write-stages` on either CLI script explodes `pipeline_trace` into one
JSON file per stage (`01_start.json` ... `NN_done.json`, plus a combined
`00_all_stages.json`) under `outputs/reports/<sample>_stages/`. This was
requested specifically so intermediate outputs (not just the final score)
are inspectable as data, not just as console text. The segmentation stage
in particular writes the guru's and the learner's segmented aksharas to
**two separate files** (`segmentation_guru_aksharas.json` and
`segmentation_learner_aksharas.json`) rather than one combined file, so
either side can be inspected, diffed, or fed elsewhere independently.
Verified in this sandbox: a text-only run produced 14 stage files with
untruncated content (`segmentation_guru_aksharas.json` contains all 29
aksharas of the full shloka line, not a preview; `segmentation_learner_
aksharas.json` likewise for the learner's 29), and an audio+ASR run
produced 16 stage files including `asr_preflight.json` (file size/lang
recorded *before* the ASR call) and `asr_transcribe_complete.json` (the
exact transcript text and elapsed decode time returned *by* the ASR
call).

### 3.3 Audio preflight check + a real bug it catches (`src/asr/base.py`)

This surfaced a genuine issue in the original code: this repo's own demo
folders (`shlokam1_responses/`, `padyam2_responses/`) intentionally
contain **0-byte placeholder `.weba` files** (see README "About the
demo"). Previously, running `--asr whisper` against those directly (i.e.
without `--demo-text-dir`) would have handed an empty file straight to
`whisper.transcribe()`, which can return `""` or noise — indistinguishable
from a normal (if bad) transcription in the output.

`preflight_check()` now rejects any audio file under ~2KB or missing with
an explicit `AudioPreflightError`, before any ASR call is made. This was
verified directly: recreating the 0-byte placeholder and running it
through `evaluate_sample()` raises the error immediately (confirmed in
the trace: the run reaches `asr_dispatch` and stops there, never reaching
`asr_preflight`'s success path or `asr_transcribe_complete`); a
realistic-sized file (11,000 bytes) passes preflight and flows through to
a real, timed transcription.

**This is the honest answer to "is audio really getting converted to
text":** the code path (`ASRBackend.transcribe_checked()` →
`preflight_check()` → `transcribe()` → logged elapsed time + transcript
preview) is now correct and was verified end-to-end with a stand-in ASR
backend (real Whisper model weights aren't downloadable in this sandbox —
see "Network limitations"). Whether it will produce *good* transcriptions
on your actual ~100 real `.weba` files depends on file integrity that
could not be checked from here — the README now includes the exact
command to check for undersized files before committing to a full batch
run:

```bash
find audios_for_pronunciation_test/audios_learners -name "*.weba" -size -2k
```

### 3.4 ASR audit summary (`batch_evaluate.py`, on by default)

After any batch run, a summary block reports (across the whole run): how
many learner files were scored via real ASR vs. a demo-text override vs.
skipped; how many were rejected by the preflight check and why; and, for
files that did go through ASR, the average decode time and transcript
length — non-trivial, file-size-correlated numbers that a stubbed/fake
backend could not produce. This makes the ASR question answerable from a
single run's console output, not just from inspecting individual JSON
files.

---

## 4. Results (on the real dataset's reference texts)

The actual `.weba`/`.mp3` audio could not be processed in this sandbox
(see §6), so the pipeline is demonstrated on the **real guru texts** for
Shlokam 1 (Sanskrit) and Padyam 2 (Telugu) with two synthetic learner
transcripts each:

| Item | Learner | Induced error | Score | Rubric 1 | Rubric 2 | Rubric 3 |
|---|---|---|---|---|---|---|
| shlokam1 (Sanskrit) | demo_perfect | none | **100.0** | 100.0 | 100.0 | 100.0 |
| shlokam1 (Sanskrit) | demo_aspiration_error | पृथिव्या→पृतिव्या (थ→त) | **99.8** | 99.7 | 100.0 | 100.0 |
| padyam2 (Telugu) | demo_perfect | none | **100.0** | 100.0 | 100.0 | 100.0 |
| padyam2 (Telugu) | demo_geminate_error | వికార→విఖార (క→ఖ) | **99.8** | 99.7 | 100.0 | 100.0 |

Both single-error cases were correctly detected, correctly isolated to
Rubric 1 only, and correctly tagged with the exact guru-vs-learner akshara
pair quoted in the report.

Additionally, for §3's observability work, a full text-only run
(`shlokam1_check`, one थ/त aspiration error induced) was traced end-to-end
with `--write-stages`: 12 stage files were produced, matching the
alignment tag counts (`{"match": 28, "substitution": 1}`) and rubric
scores independently reproduced from the raw JSON, confirming the trace
data is internally consistent with the scored report, not a separate
approximation of it.

Unit tests (`tests/test_*.py`) all pass, including the Devanagari **and**
Telugu variants of every one of Pavan's flagship examples, unaffected by
the observability changes.

## 5. What was and wasn't possible to run end-to-end here

**Fully implemented, unit-tested, and demonstrated:**
- Script-generic (Devanagari + Telugu) akshara segmentation
- Phonetic feature extraction for both scripts
- Phonetically-weighted alignment with per-error-type tagging
- All three rubrics + aggregate scoring + grading
- JSON + Markdown report generation, per-learner and per-item CSV summaries
- CLI for single-sample and full-dataset batch evaluation
- Stage-by-stage trace (console + per-stage JSON files) and the ASR audit
  summary, verified against both a text-only sample and an audio+ASR
  sample (via a stand-in backend, see below)

**Not runnable inside this sandbox, by design of its network policy:**
- Transcribing the real `.weba` learner recordings with actual Whisper
  model weights (needs general internet access this sandbox doesn't have,
  plus the real audio files, which live on your machine). The
  `transcribe_checked()` code path was instead verified with a drop-in
  fake backend that reads real file bytes and returns text through the
  identical preflight → transcribe → log sequence `WhisperASR` uses.
- The 11 reference texts here were transcribed by hand from the
  `audios_text.docx` content you shared — worth a quick spot-check against
  the original docx before running the full batch.

## 6. Audio-layer alternative (for future work)

If ASR-induced "auto-correction" of subtle mispronunciations turns out to
be a real problem in practice, the natural upgrade is a phoneme-level
recognizer (CTC-based wav2vec2, or forced alignment via
`ctc-segmentation`/Montreal Forced Aligner) feeding the *same* `align.py`
+ rubric modules — an ASR-layer swap, not a rewrite, since the phonetic
engine is already script/feature generic (`src/phonetics/scripts.py`).

## 7. Suggested next steps

1. **Run the undersized-file check before your first real batch:**
   `find audios_for_pronunciation_test/audios_learners -name "*.weba" -size -2k`
   — anything it lists needs re-recording/re-uploading, since the
   preflight check will now refuse to score it.
2. Spot-check the 11 `data/reference_texts/*_unicode.txt` files against
   the original `audios_text.docx` for any line-break/formatting drift.
3. Run `batch_evaluate.py --asr whisper --items shlokam1 --limit-per-item 2
   --verbose --write-stages` first — read the stage JSON files for those 2
   learners end-to-end to sanity-check ASR + scoring quality before
   committing to the full ~100-file bilingual run.
4. Run the full batch and read the ASR audit summary at the end; if
   "Rejected by preflight" is non-zero, address those specific files
   before trusting `overall_summary.csv`.
5. Spot-check a handful of real reports (and their `_stages/` trace, if
   `--write-stages` was used) against Pavan's own judgement of the same
   recordings, and adjust rubric weights in `config.yaml` if needed.
6. Decide on an LMS integration format for the JSON reports (current
   schema in `scoring.PariksaReport.to_dict()`, now extended with the
   `asr_*` / `learner_text_source` / `pipeline_trace` fields — happy to
   adapt field names/shape to whatever the Mana Bhasha LMS expects, and to
   drop `pipeline_trace` from the LMS-facing JSON if it's considered too
   verbose for that use, since `--write-stages` covers the same need as
   separate files).
7. If ASR auto-correction turns out to hide real errors on either
   language, prioritise the audio-layer (phoneme-CTC) alternative in §6.