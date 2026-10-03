# Uchcharana Pariksha (उच्चारण परीक्षा) — Mana Bhasha Pronunciation Test

> Web-application README: <https://github.com/kalidas-mtp-btp/ManaBhashaUchcharanaPariksha/blob/rectified_prompt_echo/web/README-web.md> (also in this repo at `web/README-web.md`).
> Design write-up, experiments, limitations and roadmap: `REPORT.md`. Formal experiment record: `EXPERIMENT.md`.

An automated pronunciation-assessment engine. It compares each **learner's recitation (audio)** of a Sanskrit shloka or Telugu padyam with the **guru's reference text**, scores it against three rubrics, and tells you **where in the audio** each error occurred. It is built to run on the real Mana Bhasha dataset: **5 Sanskrit shlokas (Devanagari) + 6 Telugu padyams (Telugu script)**, each with many learner recordings.

---

## Table of contents

1. [Project overview](#1-project-overview)
2. [The dataset](#2-the-dataset)
3. [Architecture and why comparison happens in the text layer](#3-architecture)
4. [Repository structure](#4-repository-structure)
5. [Installation](#5-installation)
6. [Quick start](#6-quick-start)
7. [Running on the real dataset](#7-running-on-the-real-dataset)
8. [Pipeline stages in detail](#8-pipeline-stages-in-detail)
9. [Phonetic engine](#9-phonetic-engine)
10. [Alignment algorithm and error tags](#10-alignment-algorithm-and-error-tags)
11. [Rubrics and scoring](#11-rubrics-and-scoring)
12. [ASR layer](#12-asr-layer)
13. [Mapping errors to audio time](#13-mapping-errors-to-audio-time)
14. [Outputs and report schema](#14-outputs-and-report-schema)
15. [Command-line reference](#15-command-line-reference)
16. [Web UI](#16-web-ui)
17. [Configuration](#17-configuration)
18. [Tests](#18-tests)
19. [Troubleshooting](#19-troubleshooting)
20. [Known limitations](#20-known-limitations)
21. [Extending the system](#21-extending-the-system)
22. [Command cheat-sheet](#22-command-cheat-sheet)
23. [Change history](#23-change-history)

---

## 1. Project overview

### 1.1 The three rubrics (from Pavan's brief)

| # | Rubric | What is checked | Example | Default weight |
|---|---|---|---|---|
| 1 | **Syllable perfection** | alpaprana vs mahaprana, sanyukta akshara (conjuncts), dvitva akshara (gemination); also generic substitutions, omissions and insertions | त/थ, త/థ · द्व्य vs ध्व्य · द्ध vs द्द, च्च vs च्छ | 0.50 |
| 2 | **Anunasika (nasalisation)** | the nasal used, and whether nasalisation is present | गङ्गा said as गम्गा / गन्गा | 0.25 |
| 3 | **Word splitting (pada-cheda)** | whether the learner's word groups match the guru's | रामच vs राम च | 0.25 |

**Tune, intonation and rhythm are deliberately not scored**, per the guru's guidance. A fixed, non-penalising note is attached to every report.

### 1.2 What the system produces

* An **overall score (0–100)** and a **grade band**.
* **Per-rubric scores** with human-readable feedback ("practise minimal pairs such as त/थ…").
* A full **akshara-by-akshara comparison** (guru vs learner, tag, cost, note).
* A list of **timed errors** — each with `start`/`end` seconds in the learner's audio — which the web UI draws on the waveform.
* A **per-stage audit trail** (ASR output, normalisation, segmentation, alignment, timing, each rubric, scoring) as JSON.
* An **ASR-quality flag** so a human knows when a score may be unreliable.

### 1.3 Two scripts, one engine

Devanagari and Telugu share the same Sanskrit-derived phonology (a 5×5 *varga* grid of stops, plus aspiration, nasals, conjunct formation with a halant/virama). A `ScriptProfile` per script (`src/phonetics/scripts.py`) supplies Unicode ranges and phonetic tables; segmentation, feature extraction and error classification are written against that profile. The script is **auto-detected** from the guru's reference text, so the only per-item setting is the ASR language code (`sa` or `te`).

### 1.4 What this is *not*

* It is **not a direct acoustic pronunciation model.** It scores the *text* an ASR system produces from the audio. Anything the ASR mis-hears, "auto-corrects" or hallucinates is indistinguishable from a learner error (see §20 and `REPORT.md` §8).
* Accuracy against human graders has **not yet been measured**; no labelled set exists (see `REPORT.md` §12).

---

## 2. The dataset

```
audios_for_pronunciation_test/
├── audios_teachers/
│   ├── sanskrit_shloka1.mp3 … sanskrit_shloka5.mp3
│   └── telugu_padyam1.mp3   … telugu_padyam6.mp3
├── audios_learners/
│   ├── shlokam1_responses/<uuid>.weba      (7–11 recordings per item)
│   ├── shlokam2_responses/ … shlokam5_responses/
│   └── padyam1_responses/  … padyam6_responses/   (7–10 recordings each)
└── audios_text/
    └── audios_text.docx                     (source of the guru reference texts)
```

| | Items | Script | Whisper language | Guru audio | Learner folders |
|---|---|---|---|---|---|
| Shlokas | 5 | Devanagari | `sa` | `sanskrit_shloka1..5.mp3` | `shlokam1..5_responses/` |
| Padyams | 6 | Telugu | `te` | `telugu_padyam1..6.mp3` | `padyam1..6_responses/` |

≈ 100 learner recordings in total. Learner files are browser-recorded WebM/Opus (`.weba`).

`audios_text.docx` has been transcribed into `data/reference_texts/<item>_unicode.txt` (native script) and `<item>_roman.txt`, one pair per item. `data/reference_texts/metadata.json` maps each item id to:

```json
"shlokam1": { "language": "Sanskrit", "script": "devanagari", "whisper_lang": "sa",
              "learner_dir": "shlokam1_responses", "...": "teacher audio filename" }
```

`batch_evaluate.py` reads `language`, `whisper_lang` and `learner_dir` from it. **The guru's audio is not needed for scoring** (the true text is already known) — it is only used in the web UI for side-by-side listening.

> The reference texts were hand-transcribed from the docx; spot-check them against the original before trusting a full run.

---

## 3. Architecture

```
 guru reference text (known) ───────────────────────────────────────────┐
                                                                          │
 learner audio ──► [Whisper, per-item language, generic script hint] ──► learner text
                              │                                           │
                              └─► word timestamps, confidence             ▼
                                                                  normalise (NFC, collapse whitespace)
                                                                          │
                                                       script detection / romanisation fallback
                                                                          │
                                                          akshara segmentation (both texts)
                                                                          │
                                         phonetically-weighted akshara alignment (edit distance)
                                              │                                │
                                              ▼                                ▼
                                   error → time-interval mapping       rubric 1 · rubric 2 · rubric 3
                                              │                                │
                                              └────────────► scoring + grade ◄─┘
                                                                  │
                                           JSON · Markdown · per-stage JSON · CSV · web UI
```

### 3.1 Why compare in the text layer

* **Dependency-light and auditable.** Every intermediate result is plain text/JSON a guru can read.
* **Testable with zero audio.** The phonetic engine is validated by unit tests on strings, in both scripts.
* **ASR-agnostic.** Swap Whisper for another recogniser by implementing one method (see §21).
* **Known ground truth.** Because the guru text is fixed, only one side needs transcribing.

### 3.2 The price of the text layer

A language-model ASR may silently repair mispronunciations, or invent errors in unclear audio. The long-term remedy is a phoneme-level recogniser with forced alignment, feeding the *same* alignment and rubric modules (`REPORT.md` §13).

---

## 4. Repository structure

```
ManaBhashaUchcharanaPariksha/
├── README.md  REPORT.md  EXPERIMENT.md
├── config.yaml                  rubric weights, ASR choice, paths (see §17 — not yet read by the scripts)
├── requirements.txt
├── audios_for_pronunciation_test/   <- your dataset (see §2)
├── data/
│   ├── reference_texts/         <item>_unicode.txt, <item>_roman.txt, metadata.json
│   └── demo_learner_texts/      shlokam1/*.txt, padyam2/*.txt (synthetic transcripts for audio-free demos)
├── src/
│   ├── asr/
│   │   ├── base.py              ASRBackend (ABC), ASRResult dataclass, NullASR
│   │   └── whisper_asr.py       WhisperASR: generic prompt, duration check, word timestamps, fallback
│   ├── phonetics/
│   │   ├── scripts.py           ScriptProfile; DEVANAGARI, TELUGU; detect_script, profile_for
│   │   ├── akshara.py           Akshara dataclass; segment_aksharas, to_words, word_index_map
│   │   ├── features.py          aspiration / nasal helpers; AksharaFeatures, extract_features
│   │   └── transliteration.py   romanised (IAST) → native script fallback
│   ├── alignment/
│   │   ├── align.py             AlignedPair; classification; DP alignment
│   │   └── timing.py            map_errors_to_time: akshara errors → audio intervals
│   ├── rubrics/
│   │   ├── rubric1_syllable_pronunciation.py
│   │   ├── rubric2_anunasika.py
│   │   └── rubric3_word_splitting.py
│   ├── pipeline.py              evaluate_sample(): orchestration; builds report["stages"]
│   ├── scoring.py               DEFAULT_WEIGHTS, grade_from_score, build_report, PariksaReport
│   ├── report_generator.py      write_json / write_markdown / write_stages_json / write_per_stage_files
│   └── stagelog.py              StageLog utility (present, but not called by the pipeline today)
├── scripts/
│   ├── run_pariksha.py          one sample (text or audio)
│   └── batch_evaluate.py        whole dataset or selected items
├── tests/                       test_akshara.py · test_features.py · test_alignment.py · test_pipeline.py
├── web/                         app.py (Flask) · static/{index.html, app.js, style.css} · uploads/
└── outputs/reports/             generated reports
```

---

## 5. Installation

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt            # includes indic-transliteration
pip install openai-whisper                  # ASR (downloads model weights on first use)
sudo apt-get install ffmpeg                 # decodes .weba/.mp3 (Whisper) and makes browser playback WAVs (web UI)
pip install -r web/requirements-web.txt     # only if you will use the web UI (Flask)
```

Notes:

* Tested on Python 3.10, CPU only. Whisper prints `FP16 is not supported on CPU; using FP32` — harmless.
* A `NumbaWarning` about the TBB threading layer is also harmless.
* On Ubuntu with system Python you may need `--break-system-packages`; inside a venv you do not.
* The default Whisper model is `small`. It is set in `WhisperASR.__init__(model_size="small")`.

---

## 6. Quick start

### 6.1 Unit tests (no audio, no network)

```bash
python tests/test_akshara.py
python tests/test_features.py
python tests/test_alignment.py
python tests/test_pipeline.py
```

### 6.2 Audio-free demo

```bash
python scripts/batch_evaluate.py --items shlokam1 padyam2 \
    --demo-text-dir data/demo_learner_texts --out-dir outputs/reports
cat outputs/reports/shlokam1/demo_aspiration_error.md
cat outputs/reports/overall_summary.csv
```

`--demo-text-dir/<item>/<learner_id>.txt` overrides ASR for any learner whose file exists, which lets the real folder-scanning logic run without real audio. The shipped demos are:

| File | Content | Expected |
|---|---|---|
| `shlokam1/demo_perfect.txt` | identical to the guru's text | 100 |
| `shlokam1/demo_aspiration_error.txt` | पृथिव्या → पृतिव्या (थ→त) | ≈ 99.8, aspiration error |
| `padyam2/demo_perfect.txt` | identical (Telugu) | 100 |
| `padyam2/demo_geminate_error.txt` | వికార → విఖార (క→ఖ) | ≈ 99.8, aspiration error |

### 6.3 One sample, text only

```bash
python scripts/run_pariksha.py --sample-id shlokam1_check \
  --guru-text-file data/reference_texts/shlokam1_unicode.txt \
  --learner-text "अस्त्युत्तरस्यां दिशि थेवतात्मा हिमालयो नाम नगाधिराजः ।"
```

### 6.4 One sample, real audio

```bash
python scripts/run_pariksha.py --sample-id demo_audio \
  --guru-text-file data/reference_texts/shlokam1_unicode.txt \
  --learner-audio path/to/learner.weba --asr whisper --lang sa     # --lang te for Telugu
```

---

## 7. Running on the real dataset

1. Place/symlink `audios_for_pronunciation_test/` at the repo root with the layout in §2.
2. Install Whisper and ffmpeg (§5).
3. Sanity check on a few files first:

   ```bash
   python scripts/batch_evaluate.py --asr whisper --items shlokam1 --limit-per-item 2 --out-dir outputs/reports
   ```
   Read `outputs/reports/shlokam1/<learner>/asr.json` and `alignment.json` for those two learners and **listen to the audio** before trusting the numbers.
4. Run everything:

   ```bash
   python scripts/batch_evaluate.py --asr whisper --out-dir outputs/reports
   ```
5. Open `outputs/reports/overall_summary.csv`; sort by `overall_score`, and review every row with `asr_flagged = True`.

What a batch prints:

```
[ok] shlokam1/20f05867-…: 73.4/100 (Needs practice (अभ्यासं करणीयम्))
[warning] shlokam1__3fc3f4e3-…: ASR backend reported low confidence / possible prompt echo. …
[ok] shlokam1/3fc3f4e3-…: 77.2/100 (Good (साधु))  [FLAGGED]

Evaluated 2 learner responses across 1 item(s). Average overall score: 75.3/100
[ATTENTION] 1 response(s) were flagged as possibly-unreliable ASR transcripts …
```

Runtime on a CPU laptop: roughly 1–2 minutes per 15-second clip with Whisper `small` (model load is a one-off cost per process). A full ~100-file run is therefore a multi-hour job.

---

## 8. Pipeline stages in detail

`pipeline.evaluate_sample(sample_id, guru_text, learner_text=None, learner_audio_path=None, asr=None, weights=None, asr_lang="sa")` returns one dict. Every stage's output is stored under `report["stages"]`.

| # | Stage key | What happens | Main contents |
|---|---|---|---|
| 1 | `asr` | If `learner_text` is not given, the backend transcribes the audio. | `mode` (`audio_transcribed` / `text_supplied`), `raw_learner_text`, `diagnostics`, `words[]`, `duration`, `flagged`, `flag_reason` |
| 2 | `normalization` | Unicode NFC; **any** run of whitespace (space/tab/newline) collapsed to one space; ends trimmed. | `guru_text`, `learner_text` |
| 3 | `script_detection` | Script detected from the guru text (error if neither Devanagari nor Telugu). If the learner text has no Indic characters but has letters, it is treated as romanised and transliterated (IAST → native). | `guru_script`, `used_transliteration_fallback`, `learner_text_after_fallback` |
| – | *(safety check)* | If audio was used, the transcript is byte-identical to the guru text, **and** ASR confidence was low → flagged. | sets `asr_flagged` |
| 4 | `segmentation` | Both texts split into aksharas. | `guru_aksharas[]`, `learner_aksharas[]` (text, consonants, vowel_sign, flags) |
| 5 | `alignment` | Weighted edit-distance alignment. | `pairs[]` (guru, learner, tag, cost, note) |
| 5b | `timing` | Errors mapped to audio intervals. | `timing_available`, `approximate`, `errors[]` |
| 6 | `rubric1`, `rubric2`, `rubric3` | Rubric computation. | scores and error lists |
| 7 | `scoring` | Weighted overall score and grade. | `overall_score`, `grade` |

Messages `[warning] … romanized …` and `[warning] … ASR … low confidence …` are printed to the console when those conditions fire.

---

## 9. Phonetic engine

### 9.1 Akshara segmentation (`src/phonetics/akshara.py`)

An **akshara** is an orthographic syllable. The segmenter walks the text once:

| Input | Result |
|---|---|
| whitespace character | its own akshara (kept so word boundaries survive) |
| consonant | starts a cluster; optional nukta; then repeated *halant + consonant* extends the cluster (`स्त्यु` = स+त+य); a trailing halant ends a "dead" consonant; otherwise an optional vowel sign (matra) attaches |
| after a consonant | anusvara, candrabindu, visarga (and avagraha/nukta) are absorbed into the same akshara |
| independent vowel (अ इ औ …) | akshara, with trailing anusvara/candrabindu/visarga |
| anything else (danda `।`, `॥`, comma, digits) | a one-character akshara with no consonants |

Each `Akshara` records: `text`, `consonants[]`, `vowel_sign`, `is_independent_vowel`, `anusvara`, `candrabindu`, `visarga`, `script`.

Examples (from tests): `गङ्गा → [ग, ङ्गा]`; `अहं → [अ(independent vowel), हं]`; `राम च कृष्ण` → 3 words.

`to_words()` groups aksharas between whitespace; `word_index_map()` gives each akshara's word index (used for timing).

### 9.2 Script profiles (`scripts.py`)

Each `ScriptProfile` holds: consonant set, vowel signs, independent vowels, halant, anusvara, candrabindu, visarga, nukta, avagraha, the **varga** table (consonant → place of articulation and position 1–5), the alpaprana and mahaprana sets, the aspiration-pair map (क↔ख, ग↔घ, …, త↔థ …), nasal consonants (ङ ञ ण न म), and the homorganic-nasal map. `detect_script()` returns the first script found in a string.

### 9.3 Features (`features.py`)

`extract_features(akshara)` yields:

| Feature | Definition |
|---|---|
| `is_conjunct` | more than one consonant in the cluster |
| `is_geminate` | more than one consonant and all identical (च्च, ద్ద) — च्छ is **not** geminate |
| `has_anusvara`, `has_candrabindu` | modifier present |
| `has_nasal_consonant` | any consonant in the cluster is a nasal (ङ ञ ण न म) |
| `is_anunasika` | anusvara **or** candrabindu **or** a nasal consonant |

> Because म and न are nasal consonants, *every* akshara containing them counts as "anunasika" for the Rubric 2 denominator (10 in shlokam1). This is intentional but broad; see §20.

---

## 10. Alignment algorithm and error tags

### 10.1 Dynamic programme (`align_aksharas`)

Standard edit distance over akshara sequences with three moves — substitution/match, deletion (guru akshara not heard) and insertion (extra learner akshara) — where costs depend on phonetics. The backtrace prefers *substitution*, then *deletion*, then *insertion* on ties.

### 10.2 Classification order (`_classify_substitution`)

Applied to each candidate guru/learner pair, **first matching rule wins**:

1. identical text → `match` (0.0)
2. both whitespace → `match` (0.0, "whitespace variant")
3. exactly one is whitespace → `missing` (guru akshara aligned to a pause) or `extra` (learner akshara aligned to a guru pause), cost 1.0 — never a phonetic category
4. **aspiration** — single consonant on both sides, same vowel sign, anusvara and candrabindu, and the consonants are an aspiration pair → `aspiration_error` (0.3), noting which direction
5. **anunasika** — same vowel sign, and either `is_anunasika` differs, or both have nasal consonants but different nasal sets → `anunasika_error` (0.4)
6. **dvitva** — either side geminate and the consonant sets/lengths differ → `dvitva_error` (0.5)
7. **conjunct** — either side a conjunct and consonant lists differ → `conjunct_error` (0.5)
8. otherwise → `substitution` (1.0)

Whitespace costs: deleting or inserting a whitespace akshara is free (0.0), so a newline in the guru text versus a space (or nothing) in ASR output never costs points.

### 10.3 Tag table

| Tag | Cost | Meaning | Feeds |
|---|---|---|---|
| `match` | 0 | identical | – |
| `aspiration_error` | 0.3 | alpaprana ↔ mahaprana of the *same* place | R1 |
| `anunasika_error` | 0.4 | nasalisation differs / different nasal | R2 only |
| `dvitva_error` | 0.5 | gemination mismatch | R1 |
| `conjunct_error` | 0.5 | consonant cluster differs | R1 |
| `substitution` | 1.0 | anything else (including vowel-sign changes, visarga, punctuation) | R1 |
| `missing` | 1.0 (0 if whitespace) | guru akshara not pronounced | R1 |
| `extra` | 1.0 (0 if whitespace) | learner added an akshara | R1 |

### 10.4 Worked example (real data, learner `3fc3f4e3`)

| Guru | Learner | Tag | Cost | Why |
|---|---|---|---|---|
| स्त्यु | स्चि | conjunct_error | 0.5 | cluster स-त-य vs स-च |
| स्यां | स्या | anunasika_error | 0.4 | anusvara dropped |
| – | म | extra | 1.0 | learner added म |
| शि | सि | substitution | 1.0 | श→स is not an aspiration pair |
| धि | दि | aspiration_error | 0.3 | mahaprana said as alpaprana |
| तो | थो | aspiration_error | 0.3 | alpaprana said as mahaprana |
| ह्य | फ्या | conjunct_error | 0.5 | different cluster |
| ॥ | । | substitution | 1.0 | punctuation (see §20) |

---

## 11. Rubrics and scoring

### 11.1 Rubric 1 — syllable pronunciation

* Counts per type: `aspiration_errors`, `conjunct_errors`, `dvitva_errors`, `other_substitutions`; plus `missing`/`extra` (cost > 0).
* Score = `max(0, 100 · (1 − Σcost / N))`, where **N = number of alignment pairs that are not `extra`** (this includes whitespace and punctuation pairs, which slightly dilutes the penalty).
* Feedback text is generated per error type (e.g. aspiration advice about feeling the puff of air; "slow the cluster down"; "hold the closure briefly").

Worked: learner `3fc3f4e3` — Σcost = 3·0.3 + 5·0.5 + 15·1.0 + 1·1.0 (extra म) = 19.4 → score 67.7 ⇒ N ≈ 60.

### 11.2 Rubric 2 — anunasika

* Denominator = number of aksharas in the **guru** text with `is_anunasika`.
* Errors = alignment pairs tagged `anunasika_error`.
* Score = `max(0, 100 · (1 − errors / denominator))`; one error in a 10-anunasika text costs 10 points.

### 11.3 Rubric 3 — word splitting

* Guru and learner texts are split on whitespace.
* If counts differ → **one** boundary error (fewer = "ran words together", more = "paused mid-word").
* If counts match → each word pair whose text differs and whose lengths differ by ≥ 2 characters is a "shifted boundary".
* Score = `max(0, 100 · (1 − errors / guru_word_count))`.
* Punctuation tokens such as `।` and `॥` count as words.

### 11.4 Overall score and grade

`overall = 0.50·R1 + 0.25·R2 + 0.25·R3` (rounded to 0.1), unless `weights` is passed to `evaluate_sample`.

| Overall | Grade |
|---|---|
| ≥ 90 | Excellent (उत्तम) |
| ≥ 75 | Good (साधु) |
| ≥ 60 | Needs practice (अभ्यासं करणीयम्) |
| < 60 | Needs significant practice (बहु अभ्यासं करणीयम्) |

Tune note: always *"Tune/intonation is not graded (per guru's guidance) …"* (the `tune_matched` argument exists but nothing computes it yet).

---

## 12. ASR layer

### 12.1 Interfaces (`src/asr/base.py`)

```python
@dataclass
class ASRResult:
    text: str
    avg_logprob: Optional[float]
    no_speech_prob: Optional[float]
    prompt_echo_suspected: bool
    diagnostics: dict
    words: list      # [{"word","start","end","probability"}]
    duration: Optional[float]

class ASRBackend(ABC):
    def transcribe(self, audio_path, lang="sa", initial_prompt=None) -> ASRResult: ...
```

`NullASR` raises with instructions; it is a placeholder for tests. A backend that returns a bare string is also tolerated (backward compatibility).

### 12.2 `WhisperASR`

1. **Audio sanity check** — loads the file with Whisper's loader; unreadable → `ValueError`; shorter than **0.3 s** → `ValueError` ("too short to transcribe reliably"). This avoids Whisper's DTW crash on near-empty audio.
2. **Generic script-hint prompt** — a small fixed Devanagari or Telugu string (e.g. "ॐ नमः शिवाय। गुरुभ्यो नमः …") is used as `initial_prompt`. The `initial_prompt` argument passed by callers is **ignored on purpose**.
3. **Decode** with `condition_on_previous_text=False`, temperature fallback `(0.0, 0.2, 0.4, 0.6, 0.8, 1.0)`, `language=lang`, `word_timestamps=True`.
4. **Fallback** — if word-timestamp alignment raises a "0 elements / reshape tensor" `RuntimeError`, retry once without word timestamps (timing then degrades to duration-based estimates).
5. **Diagnostics** — mean `avg_logprob` and `no_speech_prob` over segments, per-word probabilities, duration.
6. **Flag** `prompt_echo_suspected` = transcript equals the generic prompt **or** `avg_logprob < −1.0` **or** `no_speech_prob > 0.6`.

### 12.3 The "every learner scored 100" bug (history)

The first version passed the exact guru text as `initial_prompt`. Whisper's decoder treats that as text to continue from; on quiet or reverberant chant it often echoed the prompt back, so the transcript equalled the answer key and every rubric reported zero errors. Fixes: generic prompt, `condition_on_previous_text=False`, ASR-level confidence flag, plus an independent pipeline-level check (identical-to-guru + low confidence ⇒ flagged). Details in `REPORT.md` §6.

### 12.4 Romanisation fallback

If the ASR returns Latin-script text (no Devanagari/Telugu characters), `ensure_native_script` transliterates it from IAST into the guru's script and the report is marked `used_transliteration_fallback = true` (lower confidence). A bigger Whisper model usually avoids this.

### 12.5 Backend options

| Backend | Status | Notes |
|---|---|---|
| **Whisper** (`src/asr/whisper_asr.py`) | bundled | Easiest to install; works with `.weba`/`.mp3` via ffmpeg. `small` is weak on chanted Sanskrit (see §20). Try `medium` / `large-v3` for accuracy. |
| **Bhashini API** | not implemented | Government of India speech API, strong Indic coverage; needs network and an adapter class. |
| **IndicWav2Vec2 / phoneme-CTC** | not implemented | Best long-term: phoneme-level output is far less likely to "repair" aspiration/nasalisation errors; also enables akshara-level timestamps. |

Whichever you choose, language is passed per item automatically (`whisper_lang` from metadata in batch, `--lang` for single runs) so Telugu is never decoded with a Sanskrit hint.

---

## 13. Mapping errors to audio time

Implemented in `src/alignment/timing.py`.

1. Learner aksharas are grouped into words (same grouping Rubric 3 uses).
2. **Best case:** the ASR's word count equals our word count → word *i*'s `(start, end)` is applied to every akshara error in word *i* (`approximate = false`).
3. **Fallback:** counts differ → the total duration is split evenly across our words, and every interval is marked `approximate = true`.
4. **Omissions** (`missing`) have no learner audio; their interval is the *gap* between the previous and next timed neighbours in the alignment (always `approximate = true`, with an explanatory note).
5. **No timing at all** (text-only mode, or no word timestamps/duration) → `timing_available = false`, intervals `null`; errors are still reported.

Important precision caveat: **intervals are word-level, not akshara-level.** If a word spans 1.5 s and contains four errors, all four share that 1.5 s interval.

---

## 14. Outputs and report schema

### 14.1 Files

Per learner, under `outputs/reports/<item>/`:

| Path | Content |
|---|---|
| `<learner>.json` | full report |
| `<learner>.md` | human-readable report with comparison table, timed-error table, rubric feedback |
| `<learner>.stages.json` | `{sample_id, stages}` — all stages in one file |
| `<learner>/asr.json`, `normalization.json`, `script_detection.json`, `segmentation.json`, `alignment.json`, `timing.json`, `rubric1.json`, `rubric2.json`, `rubric3.json`, `scoring.json` | one file per stage |
| `_item_summary.csv` | one row per learner for that item |

Across the run: `outputs/reports/overall_summary.csv`. Columns: `item_id, language, learner_id, overall_score, grade, rubric1_score, rubric2_score, rubric3_score, asr_flagged, asr_flag_reason`.

`run_pariksha.py` writes `<out-dir>/<sample-id>.json|.md|.stages.json` and the per-stage folder `<out-dir>/<sample-id>/`.

### 14.2 Report fields

| Field | Type | Meaning |
|---|---|---|
| `sample_id` | str | id |
| `overall_score`, `grade` | float, str | see §11.4 |
| `rubric1/2/3` | `{name, score, errors[], feedback[]}` | |
| `tune_note` | str | non-scored note |
| `guru_text`, `learner_text` | str | normalised texts compared |
| `script` | str | `devanagari` / `telugu` |
| `used_transliteration_fallback` | bool | |
| `asr_flagged`, `asr_flag_reason` | bool, str|null | |
| `timing_available` | bool | |
| `timed_errors[]` | list | `type, guru_akshara, learner_akshara, note, start, end, approximate` |
| `alignment_preview[]` | list | `guru, learner, tag, cost, note` for every pair |
| `stages` | dict | see §8 |

`type` is one of `aspiration_error, anunasika_error, dvitva_error, conjunct_error, substitution, missing, extra`.

### 14.3 Example `asr.json` (abridged)

```json
{ "mode": "audio_transcribed",
  "raw_learner_text": "अस्चित्तर स्याम दिसिदे वतात्मा लिमाले …",
  "diagnostics": { "language": "sa", "num_segments": 1, "low_confidence": true,
                   "word_timestamps_available": true,
                   "avg_logprob": -0.450, "no_speech_prob": 0.700 },
  "words": [ { "word": "अस्चित्तर", "start": 2.22, "end": 3.58, "probability": 0.546 }, "…" ],
  "duration": 14.48, "flagged": true,
  "flag_reason": "ASR backend reported low confidence / possible prompt echo" }
```

---

## 15. Command-line reference

### 15.1 `scripts/run_pariksha.py`

| Flag | Meaning |
|---|---|
| `--sample-id` *(required)* | id used for output names |
| `--guru-text` / `--guru-text-file` | reference text (one required) |
| `--learner-text` / `--learner-text-file` | learner transcript (text-only mode) |
| `--learner-audio` | learner audio (needs `--asr whisper`) |
| `--asr {whisper,none}` | ASR backend (default `none`) |
| `--lang` | `sa` (default) or `te` |
| `--out-dir` | default `outputs/reports` |

### 15.2 `scripts/batch_evaluate.py`

| Flag | Meaning |
|---|---|
| `--audio-root` | default `audios_for_pronunciation_test` |
| `--ref-dir` | default `data/reference_texts` |
| `--out-dir` | default `outputs/reports` |
| `--asr {whisper,none}` | default `none` (then only `--demo-text-dir` learners are scored) |
| `--demo-text-dir` | text overrides per item/learner |
| `--items …` | subset of item ids (default all in `metadata.json`) |
| `--limit-per-item N` | first N files per item (sorted) |

Stage files are **always** written; there are no `--verbose`, `--write-stages` or `--no-audit-asr` options in this version.

---

## 16. Web UI

A Flask app (`web/app.py`) with a static front-end. You enter the reference text, choose the language and upload the learner's audio (optionally the guru's). It returns the report and draws the learner's waveform with a **coloured band over each error's time interval**; hover for detail, click to seek and play. Start it with `python web/app.py` and open <http://127.0.0.1:5000>.

Full documentation (endpoints, JSON response, audio handling, limitations): **`web/README-web.md`** — <https://github.com/kalidas-mtp-btp/ManaBhashaUchcharanaPariksha/blob/rectified_prompt_echo/web/README-web.md>.

---

## 17. Configuration

`config.yaml`:

```yaml
rubric_weights: { rubric1: 0.5, rubric2: 0.25, rubric3: 0.25 }
asr: { backend: whisper, whisper_model_size: small }
paths: { audio_root: audios_for_pronunciation_test, reference_texts: data/reference_texts, outputs: outputs/reports }
```

> **Current status:** the scripts do **not** read `config.yaml`. Weights default to `scoring.DEFAULT_WEIGHTS`, the Whisper size is the constructor default (`small`), and paths come from CLI flags. To change them today, pass `weights=` to `evaluate_sample`, call `WhisperASR(model_size="medium")`, or edit the defaults. Wiring the YAML in is on the roadmap.

---

## 18. Tests

| File | Covers |
|---|---|
| `test_akshara.py` | segmentation (`गङ्गा`, `बुद्धः`), word grouping, independent vowels |
| `test_features.py` | aspiration pairs and nasal/anusvara/geminate-vs-conjunct detection in **both** scripts |
| `test_alignment.py` | aspiration, sanyukta, dvitva, anunasika (गम्गा/गन्गा), perfect match, Telugu equivalents, **newline vs space is not an error** |
| `test_pipeline.py` | perfect/erroneous/word-split samples, romanised-ASR fallback, no false-positive fallback, newline-in-reference is free, **prompt-echo flag fires**, confident transcript not flagged |

The pipeline tests use fake ASR backends (`_FakeEchoWhisper`, `_FakeGoodWhisper`) so Whisper is not needed.

---

## 19. Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| Every learner scores ~100 | Answer key leaked into the ASR prompt (fixed in this version) — make sure you are on the current `whisper_asr.py` |
| `[FLAGGED]` / `asr_flagged = True` | Low ASR confidence (`avg_logprob < −1.0` or `no_speech_prob > 0.6`). Listen to the audio; consider a larger model. Note the flag can fire on usable transcripts (see `REPORT.md` §8.4) |
| "recording is only 0.xx s long" | Browser mic captured almost nothing — re-record |
| `cannot reshape tensor of 0 elements` | Whisper DTW on near-silent audio; handled by a retry without word timestamps (timings then approximate) |
| Romanised learner text, `used_transliteration_fallback` | Whisper ignored the script; try a bigger model |
| Hundreds of errors / very low score | Usually ASR garbling, not the learner; inspect `asr.json` and the audio |
| `.weba` won't play in Safari / waveform flat | Install ffmpeg so the server can make a playback WAV |
| `ImportError: openai-whisper` | `pip install openai-whisper` |
| `ValueError: Could not detect a supported script` | Guru text isn't Devanagari or Telugu |
| Web UI very slow on first request | Whisper weights load once per server process |

---

## 20. Known limitations

(Full discussion with evidence in `REPORT.md` §8.)

1. **ASR noise dominates Rubric 1** — Whisper `small` mis-hears chanted Sanskrit; many "substitutions" are not the learner's fault.
2. **Punctuation is scored** — `।`, `॥`, `,` mismatches cost up to 1.0 each; dandas also count as "words" in Rubric 3.
3. **Timing** — word-level only; "missing" gap intervals can be zero-length or inverted.
4. **ASR flag is conservative** — can fire on transcripts with decent `avg_logprob` because `no_speech_prob` is high on reverberant chant.
5. **Rubric 2 sensitivity** — small denominator (≈10); म/न-containing aksharas all count as anunasika; a labial-stop confusion (म→भ) becomes an "anunasika error".
6. **Vowel-sign errors** (ल→ले) are generic substitutions at full cost; there is no dedicated vowel rubric.
7. **No validation against human graders yet.**
8. **`config.yaml` not wired in**; `stagelog.py` unused.
9. **Uploads are never cleaned** in the web UI, and the dev server has no authentication.

---

## 21. Extending the system

**Add an ASR backend**

```python
from src.asr.base import ASRBackend, ASRResult

class MyASR(ASRBackend):
    def transcribe(self, audio_path, lang="sa", initial_prompt=None) -> ASRResult:
        text, words = my_engine(audio_path, lang)      # words: [{"word","start","end","probability"}]
        return ASRResult(text=text, words=words, duration=words[-1]["end"] if words else None)

report = evaluate_sample("id", guru_text, learner_audio_path="a.weba", asr=MyASR(), asr_lang="te")
```

**Add a script** — define a `ScriptProfile` in `scripts.py`, register it in `PROFILES`, extend `detect_script` and `transliteration._targets`.

**Change costs or categories** — edit `_classify_substitution` and the cost constants in `align.py`; the rubric modules read tags only.

**Change weights** — `evaluate_sample(..., weights={"rubric1":0.6,"rubric2":0.2,"rubric3":0.2})`.

---

## 22. Command cheat-sheet

| Goal | Command |
|---|---|
| All unit tests | `python tests/test_akshara.py && python tests/test_features.py && python tests/test_alignment.py && python tests/test_pipeline.py` |
| Text-only single sample | `python scripts/run_pariksha.py --sample-id ID --guru-text-file FILE --learner-text "..."` |
| Single sample from audio | `python scripts/run_pariksha.py --sample-id ID --guru-text-file FILE --learner-audio A.weba --asr whisper --lang sa` |
| Audio-free demo | `python scripts/batch_evaluate.py --items shlokam1 padyam2 --demo-text-dir data/demo_learner_texts` |
| Real data, quick check | `python scripts/batch_evaluate.py --asr whisper --items shlokam1 --limit-per-item 2` |
| Real data, full | `python scripts/batch_evaluate.py --asr whisper` |
| Web UI | `python web/app.py` → http://127.0.0.1:5000 |
| Find tiny/empty recordings | `find audios_for_pronunciation_test/audios_learners -name "*.weba" -size -2k` |

---

## 23. Change history

| Stage | Change |
|---|---|
| v1 | Text-layer engine, three rubrics, Devanagari + Telugu, demo texts, batch CLI |
| v2 | Whitespace/newline handling (free), romanisation fallback, stage capture |
| v3 | **Prompt-echo fix** (generic prompt, `condition_on_previous_text=False`), confidence flag, audio duration check, word-timestamp fallback |
| v4 | **Error-to-time mapping** (`timing.py`), per-stage JSON files, `timed_errors` in reports |
| v5 | **Web UI** with waveform error overlay, ffmpeg playback transcoding |
| Docs | This README rewritten to match the code (earlier text described `--verbose`, `--write-stages`, an audio preflight check and an ASR audit table that are not present in the current code) |
