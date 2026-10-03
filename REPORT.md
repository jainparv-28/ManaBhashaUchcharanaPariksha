# Report: Uchcharana Pariksha for the Mana Bhasha LMS

*Status: 3 October 2026 · Companion documents: `README.md` (usage and reference), `EXPERIMENT.md` (formal experiment record), `web/README-web.md` (web UI).*

---

## Contents

1. Problem statement
2. Dataset
3. Goals, non-goals and success criteria
4. System design
5. Detailed method
6. Development history: defects found and fixed
7. Experiments on real audio
8. Error analysis and limitations
9. Observability and auditability
10. Web interface
11. Threats to validity
12. Validation plan (how to measure real accuracy)
13. Roadmap
14. LMS integration notes
15. Risks and mitigations
16. Appendices (schemas, cost tables, glossary, inventories)

---

## 1. Problem statement

Pavan's email asks for a pronunciation test (*uchcharana pariksha*) that compares a learner's recitation of a shloka or padyam with the guru's reference, graded on three rubrics:

1. **Syllable-level perfection** — alpaprana vs mahaprana (त/थ), sanyukta akshara / conjunct errors (द्व्य→ध्व्य, ग्भ्य→ग्ब्य), and dvitva akshara / gemination errors (द्ध→द्द; distinguishing च्च from च्छ).
2. **Anunasika** — e.g. गङ्गा rendered as गम्गा or गन्गा.
3. **Word splitting (pada-cheda)** — matching the guru's segmentation of the recitation into words.

Explicitly **out of scope:** tune, intonation, rhythm.

The practical need is an LMS component that, for each learner response, returns a score, readable feedback, and — added during development — *where* in the recording each error occurred, so a teacher can listen to exactly the problematic stretch.

## 2. Dataset

| | Items | Script | Reference audio | Learner responses |
|---|---|---|---|---|
| Shlokas | 5 (Sanskrit) | Devanagari | `sanskrit_shloka1..5.mp3` | `shlokam1..5_responses/` — 7–11 `.weba` each |
| Padyams | 6 (Telugu) | Telugu | `telugu_padyam1..6.mp3` | `padyam1..6_responses/` — 7–10 `.weba` each |

Roughly 100 learner recordings in two languages, one reference text per item (extracted from `audios_text.docx`). Learner files are browser-recorded WebM/Opus. Shlokam1 (the item used in all real-audio runs so far) is:

> अस्त्युत्तरस्यां दिशि देवतात्मा हिमालयो नाम नगाधिराजः । पूर्वापरौ तोयनिधी वगाह्य स्थितः पृथिव्या इव मानदण्डः ॥

It has 15 whitespace-separated tokens (13 words plus the two dandas), ~60 aksharas including spaces and 10 aksharas that count as anunasika.

## 3. Goals, non-goals and success criteria

**Goals**

* G1. Score real learner audio against a known text on the three rubrics.
* G2. Support Devanagari and Telugu with one engine.
* G3. Be auditable: every intermediate result inspectable.
* G4. Locate each error in time and display it.
* G5. Never silently report a trustworthy-looking score from an unreliable transcript.

**Non-goals (for now)**

* Scoring tune, rhythm or voice quality.
* Acoustic (phoneme-level) modelling.
* Real-time/streaming assessment.

**Success criteria (proposed)**

| Criterion | Target | Status |
|---|---|---|
| Scores vary with real speech (not 100 for all) | yes | ✅ met |
| Timestamps for ≥ 90 % of errors | yes | ✅ met in runs so far (word timestamps present) |
| Agreement with guru on error/no-error per akshara | to be set after labelling | ⏳ unmeasured |
| Overall-score agreement with guru grade bands | to be set | ⏳ unmeasured |
| Full dataset processed without crashes | yes | ⏳ not yet run (only 3 recordings) |

---

## 4. System design

### 4.1 Overview

```
guru text ───────────────────────────────────────────────┐
learner audio ─► Whisper (lang, generic prompt) ─► text ─┤
                      └► word times, confidence          ▼
                                                   normalise → script detect / romanise fallback
                                                              → akshara segmentation
                                                              → weighted alignment
                                                   ┌──────────┴───────────┐
                                           error→time mapping      rubrics 1/2/3
                                                   └──────────┬───────────┘
                                                        score + grade → JSON / MD / stages / CSV / web
```

### 4.2 Key design decisions and rationale

| Decision | Rationale | Trade-off |
|---|---|---|
| **Compare in the text layer** | Ground truth is known; cheap, transparent, testable without audio | ASR errors leak into scores (§8) |
| **One engine, `ScriptProfile` per script** | Devanagari and Telugu share structure; avoids duplicate code | Needs a profile for any new script |
| **Akshara units, not characters** | One akshara spans several code points; plain diffs mislabel errors | Rule-based segmenter must handle edge cases |
| **Phonetically weighted edit distance** | Gives the right *rubric label* straight from the backtrace; aspiration slips cost less than a wrong syllable | Costs (0.3/0.4/0.5/1.0) are judgemental, not yet calibrated |
| **Whitespace is free** | Reference text may have line breaks; ASR never does | Whitespace pairs dilute Rubric 1's denominator slightly |
| **Never give Whisper the answer** | Prompting with the guru text caused the 100 % bug | Whisper may lose script/register bias on some clips |
| **Flag, don't hide, unreliable ASR** | A human must know when to listen | The flag is noisy (§8.4) |
| **Word-level timing** | All Whisper offers | Coarser than akshara-level (§8.3) |
| **One JSON per stage** | Different consumers need different stages; audits are easy | More files per learner |

### 4.3 Components

| Module | Responsibility |
|---|---|
| `src/asr/base.py`, `whisper_asr.py` | ASR interface; Whisper backend with prompt-echo mitigation, duration check, word timestamps and a retry path |
| `src/phonetics/scripts.py` | Unicode ranges, varga table, aspiration pairs, nasals per script |
| `src/phonetics/akshara.py` | Segmentation into aksharas and words |
| `src/phonetics/features.py` | Aspiration/nasal/geminate/conjunct features |
| `src/phonetics/transliteration.py` | IAST → native script fallback |
| `src/alignment/align.py` | Classification and dynamic-programming alignment |
| `src/alignment/timing.py` | Error → audio interval mapping |
| `src/rubrics/*` | Three rubric computations |
| `src/scoring.py` | Weights, grade bands, report object |
| `src/pipeline.py` | Orchestration and stage capture |
| `src/report_generator.py` | JSON, Markdown, stage-JSON writers |
| `scripts/*` | CLIs |
| `web/*` | Flask API + browser UI |

---

## 5. Detailed method

### 5.1 Normalisation

NFC Unicode normalisation, then every whitespace run (space, tab, newline) collapsed to one space. This single step prevents line breaks in the typed reference from being counted as errors against ASR output (a bug fixed in development, §6). Punctuation is **not** removed (see §8.2).

### 5.2 Akshara segmentation

A single left-to-right pass: a consonant begins a cluster; *halant + consonant* extends it; a trailing halant ends a dead consonant; otherwise an optional vowel sign attaches; anusvara/candrabindu/visarga/nukta are absorbed; independent vowels and any other character (danda, comma) become their own units; whitespace is kept as a unit so word boundaries remain recoverable. Example: `स्त्यु` → consonants `[स, त, य]`, vowel sign `ु`.

### 5.3 Features

| Feature | Rule |
|---|---|
| Conjunct | > 1 consonant |
| Geminate | > 1 consonant, all identical (च्च yes; च्छ no) |
| Nasal consonant | member of {ङ ञ ण न म} (Telugu equivalents) |
| Anunasika | anusvara ∨ candrabindu ∨ nasal consonant |

### 5.4 Alignment costs and rule order

| Rule (first match wins) | Tag | Cost |
|---|---|---|
| identical | match | 0 |
| both whitespace | match | 0 |
| exactly one whitespace | missing / extra | 1.0 |
| single consonant each side, same vowel sign/anusvara/candrabindu, aspiration partners | aspiration_error | 0.3 |
| same vowel sign and nasal feature differs (or different nasal set) | anunasika_error | 0.4 |
| a geminate involved and consonants differ | dvitva_error | 0.5 |
| a conjunct involved and consonants differ | conjunct_error | 0.5 |
| otherwise | substitution | 1.0 |
| deletion / insertion of a non-space akshara | missing / extra | 1.0 |
| deletion / insertion of whitespace | — | 0 |

The DP minimises total cost; on ties the backtrace prefers substitution over deletion over insertion.

### 5.5 Rubrics

| Rubric | Formula | Notes |
|---|---|---|
| R1 | `100·(1 − Σcost/N)`, N = non-`extra` pairs | Σ over aspiration, conjunct, dvitva, substitution, missing, extra |
| R2 | `100·(1 − e/A)`, e = anunasika errors, A = anunasika aksharas in guru text | A = 10 for shlokam1 |
| R3 | `100·(1 − b/W)`, b = boundary errors, W = guru word tokens | one error if counts differ; per-word shift check if equal |
| Overall | `0.50·R1 + 0.25·R2 + 0.25·R3` | grade ≥ 90 / 75 / 60 |

### 5.6 ASR configuration

Whisper `small`, FP32 on CPU, language per item, fixed generic prompt, `condition_on_previous_text=False`, temperature fallback ladder, word timestamps on (retry without on DTW failure). Recordings under 0.3 s are rejected. Flag if `avg_logprob < −1.0` or `no_speech_prob > 0.6`.

### 5.7 Error → time mapping

Word-level timestamps are assigned to akshara errors by word index. If ASR and akshara word counts differ, duration is split evenly and flagged approximate. Omissions take the gap between neighbouring timed errors. Details and caveats: §8.3.

---

## 6. Development history: defects found and fixed

| # | Symptom | Root cause | Fix | Evidence |
|---|---|---|---|---|
| 1 | **Every learner scored 100** | `initial_prompt = guru_text`; Whisper echoed it on quiet/reverberant chant, so transcript ≡ answer key | Generic per-script prompt; `condition_on_previous_text=False`; ASR-level confidence flag; second pipeline-level check; regression test with a fake echo backend | Real runs now give 73–80; `test_pipeline_flags_suspected_prompt_echo` |
| 2 | Line breaks in the reference counted as errors | ASR output never contains newlines | Whitespace collapsed in `_normalize`; whitespace-vs-whitespace is a free match; whitespace-vs-akshara classed as missing/extra (not as a phonetic error) | `test_newline_vs_space_not_an_error`, `test_pipeline_newline_in_reference_text_is_free` |
| 3 | Nonsense tags such as an "anunasika error" between a space and a consonant; null timestamps | Whitespace paired with an akshara fell through to feature classifiers | Explicit one-side-whitespace branch → missing/extra, routed through gap logic in `timing.py` | alignment code comments |
| 4 | Whisper crash `cannot reshape tensor of 0 elements` | DTW word alignment on very short / silent audio | Duration check (< 0.3 s rejected) and one retry without word timestamps | `_transcribe_with_fallback` |
| 5 | Romanised ASR output (e.g. "Ṣītāṁ Ṣāṁ …") | Whisper ignored the script | IAST transliteration fallback + report flag; script hint prompt | `test_pipeline_romanized_asr_fallback` |
| 6 | Errors had no location | Only text-level scoring existed | `timing.py`, `timed_errors`, per-word timestamps from Whisper | `timing.json`, web overlay |
| 7 | `.weba` would not play / decode in some browsers | WebM support varies; wrong MIME type | ffmpeg transcode to `*_playback.wav`; register `.weba` MIME | web README |
| 8 | Documentation described features not in the code | README drifted from implementation | This rewrite | — |

---

## 7. Experiments on real audio

> Only **three recordings, all from shlokam1**, have been run on real audio. No Telugu real audio and no human grading yet. See `EXPERIMENT.md` for the formal record.

### 7.1 Setup

| Item | Value |
|---|---|
| Machine | Dell Precision 5550, CPU only |
| Python / Whisper | 3.10 / `small` (FP32) |
| Reference | shlokam1 (Devanagari) |
| Run A | `batch_evaluate.py --asr whisper --items shlokam1 --limit-per-item 2` (first two learner files, sorted) |
| Run B | Web UI, one learner file + guru mp3 (guru audio not scored) |

### 7.2 Scores

| Run | Learner | Overall | Grade | R1 | R2 | R3 | ASR flag |
|---|---|---|---|---|---|---|---|
| A | 20f05867-eaf1-4d9c-b703-704188acd4d6 | **73.4** | Needs practice | 60.2 | 80.0 | 93.3 | no |
| A | 3fc3f4e3-6d30-46e3-93ba-cb23db457f86 | **77.2** | Good | 67.7 | 80.0 | 93.3 | yes |
| B | f7498b97… (web session) | **80.3** | Good | 69.0 | 90.0 | 93.3 | not displayed |
| | **Mean** | **77.0** | | 65.6 | 83.3 | 93.3 | |

Arithmetic check: 0.5·67.7 + 0.25·80 + 0.25·93.3 = 77.2; 0.5·69 + 0.25·90 + 0.25·93.3 = 80.3.

Run A took ≈ 2 minutes for the two files including model load; Run B took 2 min 16 s from page load to result (21:08:07 → 21:10:23), mostly Whisper on CPU.

### 7.3 Run A, learner 3fc3f4e3 — transcript

| | Text |
|---|---|
| Guru | अस्त्युत्तरस्यां दिशि देवतात्मा हिमालयो नाम नगाधिराजः । पूर्वापरौ तोयनिधी वगाह्य स्थितः पृथिव्या इव मानदण्डः ॥ |
| Whisper | अस्चित्तर स्याम दिसिदे वतात्मा लिमाले यो नामना का दिराजा, और्वा परोथो यनितिवाखाफ्या स्तितष्प्र दिव्या इवभान धन्दाः। |

Whisper reports 16 words over 14.48 s with speech starting at 2.22 s (2.2 s leading silence), `avg_logprob = −0.450`, `no_speech_prob = 0.700` (hence the flag), mean word probability 0.70.

### 7.4 Per-word timing and confidence (learner 3fc3f4e3)

| # | Whisper word | Start–end (s) | Prob. | Errors timed to this word |
|---|---|---|---|---|
| 1 | अस्चित्तर | 2.22–3.58 | 0.546 | 1 |
| 2 | स्याम | 3.58–4.22 | 0.717 | 2 |
| 3 | दिसिदे | 4.22–4.76 | 0.713 | 1 |
| 4 | वतात्मा | 4.76–5.70 | 0.797 | 0 |
| 5 | लिमाले | 5.70–6.52 | 0.613 | 2 |
| 6 | यो | 6.52–6.70 | 0.846 | 0 |
| 7 | नामना | 6.70–7.32 | 0.775 | 1 |
| 8 | का | 7.32–7.52 | 0.675 | 1 |
| 9 | दिराजा, | 7.52–8.16 | 0.738 | 3 |
| 10 | और्वा | 8.52–9.26 | 0.750 | 1 |
| 11 | परोथो | 9.26–9.96 | 0.721 | 2 |
| 12 | यनितिवाखाफ्या | 9.96–11.52 | 0.579 | 4 |
| 13 | स्तितष्प्र | 11.52–12.26 | 0.725 | 3 |
| 14 | दिव्या | 12.26–12.92 | 0.816 | 1 |
| 15 | इवभान | 12.92–13.60 | 0.726 | 1 |
| 16 | धन्दाः। | 13.60–14.48 | 0.505 | 3 |
| | | | | **26** |

Observation: the words with the lowest probability (धन्दाः। 0.51, अस्चित्तर 0.55, यनितिवाखाफ्या 0.58, लिमाले 0.61) carry 3, 1, 4 and 2 errors — consistent with ASR uncertainty being a major source of "errors", though a larger sample is needed to quantify this.

### 7.5 Error profile, learner 3fc3f4e3

| Type | Count | Cost each | Examples |
|---|---|---|---|
| Aspiration | 3 | 0.3 | धि→दि, तो→थो, द→ध |
| Conjunct | 5 | 0.5 | स्त्यु→स्चि, ह्य→फ्या, स्थि→स्ति, पृ→ष्प्र, ण्डः→न्दाः |
| Dvitva | 0 | 0.5 | — |
| Other substitution | 15 | 1.0 | शि→सि, हि→लि, ल→ले, न→ना, गा→का, जः→जा, पू→औ, रौ→रो, धी→ति, व→वा, गा→खा, तः→त, थि→दि, **`।`→`,`**, **`॥`→`।`** |
| Extra | 1 | 1.0 | म inserted |
| Anunasika (R2) | 2 | 10 pts each | स्यां→स्या, मा→भा |
| Word-boundary (R3) | 1 | 6.7 pts | 16 vs 15 word groups |
| **Total timed errors** | **26** | | |

Rubric 1 arithmetic: 3·0.3 + 5·0.5 + 15·1.0 + 1·1.0 = 19.4 → 100·(1 − 19.4/60) ≈ 67.7.

### 7.6 Run B error profile (web UI)

24 timed errors over 1.74–20.00 s: 11 substitution, 5 conjunct (one being `॥`→`न्धाः`), 2 aspiration (धि→दि, थि→ति), 1 dvitva (त्त→व्त), 1 anunasika (स्यां→स्या), 1 extra, **3 missing** (जः, इ, ण्डः). R2 = 90 (one error / 10). Two of the three "missing" intervals were defective: `10.12s ~ – 7.70s` (inverted) and `17.90s ~ – 17.90s` (zero length).

### 7.7 Expected vs observed

| Expectation | Observed | Verdict |
|---|---|---|
| Scores no longer 100 | 73.4–80.3 | ✅ |
| Different learners → different outcomes | yes | ✅ |
| Devanagari output (no romanisation) | `used_transliteration_fallback = false` | ✅ |
| Word timestamps available | yes | ✅ |
| ASR word count = our word count (exact timing) | 16 = 16, `approximate = false` | ✅ |
| Transcript reasonably close to the guru's | ~46 % of non-space guru aksharas matched exactly (21 of 46) | ⚠️ |
| Punctuation / line breaks free | line breaks free ✅; danda/comma costed ❌ | ❌ |
| Valid time interval for every error | inverted and zero-length gaps for "missing" | ⚠️ |
| Flag only on unreliable ASR | fired with `avg_logprob = −0.45` | ⚠️ |
| R3 reflects splitting only | danda counted as a word | ⚠️ |
| Web UI plays audio and renders overlay | HTTP 200/206, wavs served | ✅ |

---

## 8. Error analysis and limitations

### 8.1 ASR noise dominates Rubric 1

Whisper `small` is not tuned for chanted Sanskrit. In the transcript above many substitutions (शि→सि, हि→लि, गा→का, पू→औ, रौ→रो) are phonetically odd and probably reflect mis-hearing, not the learner's articulation. The text layer cannot tell them apart. **Consequence:** at present Rubric 1 is better read as a *transcript-fidelity* score than a validated pronunciation score. **Mitigations:** larger Whisper models; Indic-tuned ASR; phoneme-level CTC + forced alignment (§13); human spot-checks of flagged and borderline cases.

### 8.2 Punctuation scored as pronunciation

Dandas and commas are not spoken sounds, yet `।`→`,` and `॥`→`।` were each costed at 1.0 (together ≈ 3 points of Rubric 1 for a 60-pair denominator), and in Run B `॥` was classified as a *conjunct error* against `न्धाः` (because the conjunct rule fires when either side is a conjunct and consonant lists differ). In Rubric 3, `।` and `॥` count as two of 15 "words". **Fix (recommended, ~5 lines):** remove or ignore `[।॥,.;:?!]` during normalisation, before segmentation; drop punctuation-only tokens from word counts.

### 8.3 Timing precision and defects

* **Word-level granularity.** All errors in a word share its interval; the 1.56-second word `यनितिवाखाफ्या` carries four errors.
* **Gap intervals for omissions** are derived from neighbours and are sometimes **inverted** (start > end) or **zero-length**. Likely cause: the neighbour search runs over the filtered error list, not over time-ordered words, so neighbours can come from unrelated positions. **Fix:** when `prev_end > next_start`, set both to the shared boundary; when equal, widen to a small epsilon; always mark approximate.
* **Merged ASR words** (e.g. `यनितिवाखाफ्या`) make several guru words collapse into one interval, which is correct for the transcript but misleading for the learner.
* **Fallback timing** (even split) is only a rough guide and is clearly marked approximate.

### 8.4 ASR-confidence flag is noisy and mislabelled

Run A's flagged learner had `avg_logprob = −0.45` (not poor) but `no_speech_prob = 0.70`. On reverberant chant `no_speech_prob` is often high even though speech is plainly present. The flag text says *possible prompt echo*, which is misleading when the real issue is general low confidence (and, since the prompt is now generic, true echo of the answer key is no longer possible). **Fix:** base the flag on `avg_logprob` and the fraction of words below a probability threshold, reword the message, and keep the byte-identical-to-guru check, which is still valuable.

### 8.5 Rubric 2 sensitivity and breadth

* Every akshara containing म or न counts as "anunasika", so the denominator is broad (10 in shlokam1) and each error costs 10 points.
* `मा→भा` (a labial nasal heard as a labial stop) is tagged as an anunasika error — plausible, but also a very typical ASR confusion.
* Substituting one nasal for another where the vowel sign differs falls through to a generic substitution and is not counted in R2.

### 8.6 Other limitations

| # | Limitation | Impact |
|---|---|---|
| 1 | Vowel-sign errors (ल→ले, रौ→रो) are generic substitutions at full cost | Over-penalises vowel length/quality slips relative to aspiration slips; no vowel rubric |
| 2 | Visarga and anusvara drops on non-nasal aksharas are generic substitutions | Visarga (जः→जा) not separately reported |
| 3 | Rubric 1's denominator includes whitespace/punctuation pairs | Scores slightly higher than a pure akshara ratio |
| 4 | Rubric 3 treats count differences as a single error | Cannot distinguish one merged word from five |
| 5 | Costs (0.3/0.4/0.5/1.0) and weights (50/25/25) are uncalibrated | Scores are not comparable to a human scale yet |
| 6 | `config.yaml` is not read by scripts; Whisper size fixed in code | Surprise when editing YAML |
| 7 | `stagelog.py` present but unused | Dead code |
| 8 | `model_size` in `asr.json` shows `null` | Cosmetic |
| 9 | Web UI keeps all uploads; no auth; dev server | Not production-safe |
| 10 | CPU Whisper is slow (~2 min per 15 s clip) | A ~100-file batch takes hours; consider GPU |
| 11 | Reference texts hand-transcribed | Possible typos propagate into scores |
| 12 | Only 3 real recordings tested, no Telugu | Unknown behaviour on padyams |

---

## 9. Observability and auditability

Every stage of `evaluate_sample` writes its output into `report["stages"]`, and `report_generator` persists it both combined (`<id>.stages.json`) and as one JSON per stage:

| Stage file | Answers the question |
|---|---|
| `asr.json` | What did Whisper hear? How confident was it? Per-word times and probabilities? |
| `normalization.json` | What exact strings were compared? |
| `script_detection.json` | Which script? Was romanised text transliterated? |
| `segmentation.json` | How were both texts split into aksharas? |
| `alignment.json` | Which guru akshara was paired with which learner akshara, with tag, cost and note? |
| `timing.json` | Where in the audio is each error? Exact or approximate? |
| `rubric1/2/3.json` | Which errors fed each rubric? |
| `scoring.json` | Final score and grade |

This answered the question "is the audio really being converted to text?": `asr.json` shows non-trivial, learner-specific transcripts, per-word timestamps and confidences that differ between learners — evidence that audio was genuinely decoded (a stub could not produce them).

*Earlier drafts of the documentation described `--verbose`, `--write-stages`, an audio-size preflight check, a `transcribe_checked()` wrapper and an ASR audit table. These are not in the present code; the 0.3-second duration check in `WhisperASR` and the always-on stage files cover the same ground. `stagelog.py` could be adopted later for console tracing.*

## 10. Web interface

A Flask backend calls `evaluate_sample()` exactly as the CLI does and returns the report with audio URLs; the browser decodes audio with the Web Audio API, draws a min/max waveform on a `<canvas>`, overlays a colour-coded band for every timed error, and offers hover tooltips, click-to-seek, a sortable error table and warning banners (ASR flag, romanisation, missing timestamps, missing ffmpeg). ffmpeg produces a PCM WAV for playback (Safari cannot decode WebM) while the original file is what Whisper scores. Endpoint and field details are in `web/README-web.md`.

Observed behaviour: page and assets served (200), `POST /api/evaluate` 200, learner and guru WAVs served with range requests (200/206). Results rendered with the colour legend and 24 timed errors.

---

## 11. Threats to validity

| Threat | Description | Mitigation |
|---|---|---|
| Construct validity | The score measures transcript fidelity, not articulation | Human validation; phoneme-level ASR |
| Sample size | 3 recordings, one item, one language | Run the whole dataset; add Telugu |
| Single ASR model | Results depend on Whisper `small` | Compare `medium`/`large-v3` and Indic ASR |
| Cost calibration | Weights chosen by judgement | Fit/tune against guru ratings |
| Reference text accuracy | Hand transcription | Proof-read against the docx |
| Recording conditions | Phone mics, reverberation | Report `avg_logprob` per learner; flag poor audio |
| Learner variability | Different recitation speeds/tunes | Tune not scored; word-level (not time-aligned) comparison is speed-independent |

## 12. Validation plan (how to measure real accuracy)

1. **Pick a pilot set:** 2 items (1 shloka, 1 padyam) × 8 learners ≈ 16 recordings.
2. **Guru annotation:** for each recording the guru marks, per guru akshara, one of {correct, aspiration, nasal, conjunct/gemination, other, omitted} and the intended word boundaries; optionally an overall grade band.
3. **Metrics:**
   * Per-akshara precision/recall/F1 of "is an error" and per category.
   * Per-rubric correlation (Spearman) between system score and guru-derived score.
   * Grade-band agreement (accuracy, Cohen's κ).
   * Time-interval hit-rate: fraction of true errors whose interval overlaps the system's.
4. **Ablations:** punctuation stripped vs not; Whisper `small` vs `medium` vs `large-v3`; phoneme-CTC recogniser; cost vectors.
5. **Acceptance:** agree thresholds with the guru up front (e.g. κ ≥ 0.6 on grade bands, error recall ≥ 0.7).
6. **Report:** add the results to `EXPERIMENT.md` as a second experiment.

## 13. Roadmap

| Priority | Item | Effort | Benefit |
|---|---|---|---|
| P0 | Strip punctuation in normalisation; ignore punctuation tokens in R3 | hours | Removes ~3 spurious points and false conjunct errors |
| P0 | Clamp inverted/zero-length "missing" intervals | hours | Correct timestamps in UI |
| P0 | Pilot validation set (§12) | days | First real accuracy numbers |
| P1 | Rework ASR flag (logprob + word-probability based, clearer message) | hours | Fewer false alarms |
| P1 | Larger Whisper / GPU run; compare transcripts | days | Less ASR noise |
| P1 | Wire `config.yaml` (weights, model size, paths) | hours | Config actually works |
| P1 | Per-learner "ASR confidence" column in `overall_summary.csv` | hours | Easier triage |
| P2 | Dedicated vowel-sign / visarga categories | days | Better feedback |
| P2 | Rubric 2 denominator and weighting review | days | Less brittle R2 |
| P2 | Upload cleanup, auth and WSGI server for web UI | days | Deployable |
| P3 | Phoneme-level CTC recogniser + forced alignment | weeks | Real pronunciation scoring; akshara-level timestamps |
| P3 | Use the guru's audio (acoustic comparison / DTW) | weeks | Independent second signal |
| P3 | LMS API and batch queue | weeks | Production integration |

## 14. LMS integration notes

* The JSON report (`PariksaReport.to_dict()` plus `guru_text`, `learner_text`, `script`, `asr_flagged`, `asr_flag_reason`, `timing_available`, `timed_errors`, `alignment_preview`, `stages`) is the integration contract; the web endpoint returns a trimmed subset with audio URLs.
* For LMS display, `rubric*.feedback` is student-facing text; `timed_errors` drives "listen to this part" links; `asr_flagged` should gate whether a score is shown automatically or sent for teacher review.
* `stages` is large; drop it from the LMS-facing payload if size matters (it is also available as separate files).
* Decide with the LMS team: authentication, storage of audio, retention, and whether to surface `grade` strings (they include Sanskrit text).

## 15. Risks and mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Scores mistaken for validated pronunciation grades | high | high | Label as *preliminary*; show `asr_flagged`; validate (§12) |
| ASR repairs a real mistake ("auto-correct") | medium | medium | Phoneme-level ASR; guru spot-checks |
| ASR hallucinates errors | high on noisy audio | medium | Confidence flag; larger model |
| Telugu behaves differently from Sanskrit | medium | medium | Pilot Telugu early |
| Long runtimes | high on CPU | low | GPU or overnight batch |
| Personal data in learner recordings | medium | high | Retention policy, access control, cleanup of `web/uploads` |

---

## 16. Appendices

### A. Report JSON (abridged)

```json
{
  "sample_id": "…", "overall_score": 77.2, "grade": "Good (साधु)",
  "rubric1": {"name": "Syllable pronunciation (aspiration / sanyukta / dvitva)", "score": 67.7, "errors": [...], "feedback": [...]},
  "rubric2": {"name": "Anunasika (nasalisation)", "score": 80.0, "errors": [...], "feedback": [...]},
  "rubric3": {"name": "Word splitting (pada-cheda)", "score": 93.3, "errors": [...], "feedback": [...]},
  "tune_note": "Tune/intonation is not graded …",
  "guru_text": "…", "learner_text": "…", "script": "devanagari",
  "used_transliteration_fallback": false,
  "asr_flagged": true, "asr_flag_reason": "ASR backend reported low confidence / possible prompt echo",
  "timing_available": true,
  "timed_errors": [{"type": "conjunct_error", "guru_akshara": "स्त्यु", "learner_akshara": "स्चि",
                    "note": "…", "start": 2.22, "end": 3.58, "approximate": false}],
  "alignment_preview": [{"guru": "अ", "learner": "अ", "tag": "match", "cost": 0.0, "note": ""}],
  "stages": {"asr": {}, "normalization": {}, "script_detection": {}, "segmentation": {},
             "alignment": {}, "timing": {}, "rubric1": {}, "rubric2": {}, "rubric3": {}, "scoring": {}}
}
```

### B. Colour code in the web UI

| Type | Colour |
|---|---|
| aspiration_error | red `#e63946` |
| anunasika_error | orange `#f4a261` |
| dvitva_error | purple `#9c6ade` |
| conjunct_error | blue `#457b9d` |
| substitution | grey `#6c757d` |
| missing | near-black `#111318` |
| extra | teal `#2a9d8f` |

### C. Test inventory

| Test file | Tests |
|---|---|
| `test_akshara.py` | simple word, geminate, word split, independent vowel |
| `test_features.py` | aspiration pairs (Dev/Tel), anunasika detection (Dev/Tel), geminate vs conjunct (Dev/Tel) |
| `test_alignment.py` | alpaprana/mahaprana, sanyukta, dvitva, anunasika, perfect match, Telugu aspiration/geminate/perfect, newline vs space |
| `test_pipeline.py` | perfect, with errors, word split, romanised fallback, no false-positive fallback, newline free, echo flagged, confident not flagged |

### D. Glossary

| Term | Meaning |
|---|---|
| Akshara | orthographic syllable (consonant cluster + vowel sign + modifiers) |
| Alpaprana / Mahaprana | unaspirated / aspirated stop (त / थ) |
| Anunasika | nasalisation (anusvara, candrabindu, nasal consonant) |
| Sanyukta akshara | conjunct (consonant cluster joined by halant) |
| Dvitva | gemination (doubled consonant, e.g. द्द) |
| Pada-cheda | splitting a verse into its words |
| Varga | the 5×5 grid of stops by place of articulation |
| Halant / virama | sign suppressing a consonant's inherent vowel |
| Shloka / Padyam | Sanskrit / Telugu verse |
| Guru | teacher whose rendition is the reference |
| Prompt echo | ASR repeating its prompt instead of transcribing |
| DTW | dynamic time warping (Whisper's word-timestamp method) |
| CTC | connectionist temporal classification (phoneme-level ASR training) |

### E. File inventory (code)

| File | Purpose |
|---|---|
| `src/asr/base.py` | `ASRResult`, `ASRBackend`, `NullASR` |
| `src/asr/whisper_asr.py` | Whisper backend and mitigations |
| `src/phonetics/scripts.py` | script profiles |
| `src/phonetics/akshara.py` | segmentation helpers |
| `src/phonetics/features.py` | phonetic features |
| `src/phonetics/transliteration.py` | romanised-text fallback |
| `src/alignment/align.py` | classification and DP alignment |
| `src/alignment/timing.py` | error→time |
| `src/rubrics/rubric1_syllable_pronunciation.py` | R1 |
| `src/rubrics/rubric2_anunasika.py` | R2 |
| `src/rubrics/rubric3_word_splitting.py` | R3 |
| `src/pipeline.py` | orchestration |
| `src/scoring.py` | scoring and grades |
| `src/report_generator.py` | writers |
| `src/stagelog.py` | unused trace utility |
| `scripts/run_pariksha.py`, `batch_evaluate.py` | CLIs |
| `web/app.py`, `web/static/*` | web app |

### F. Next-step checklist for the team

1. Apply the two P0 fixes (punctuation, gap intervals) and re-run Run A to see the effect.
2. Listen to the two Run A recordings and the Run B recording; note which flagged "errors" are real.
3. Run `batch_evaluate.py --asr whisper --items padyam2 --limit-per-item 2` to see behaviour on Telugu.
4. Prepare the pilot annotation sheet (§12).
5. Decide GPU availability for the full run.
6. Agree LMS payload and review workflow (§14).
