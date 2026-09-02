#!/usr/bin/env python3
"""
batch_evaluate.py
------------------
Evaluate the REAL Mana Bhasha dataset layout (see original docstring in
README/REPORT for the folder structure).

MODIFIED:
  --verbose        prints every pipeline stage (guru text -> ASR ->
                    normalize -> script detect -> segmentation -> alignment
                    -> rubrics -> report) for every sample as it runs.
  --audit-asr       (default on) after the run, prints a summary table
                    proving, per item, how many learner responses were
                    actually scored from real ASR-on-audio vs. from a
                    demo-text override vs. skipped, plus flags any
                    suspiciously small/empty audio files that were
                    refused by the ASR preflight check (see src/asr/base.py).
"""
import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.pipeline import evaluate_sample
from src.report_generator import write_json, write_markdown, write_stage_files
from src.asr.base import AudioPreflightError, MIN_PLAUSIBLE_AUDIO_BYTES

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
DEFAULT_REF_DIR = os.path.join(REPO_ROOT, "data", "reference_texts")
DEFAULT_AUDIO_ROOT = os.path.join(REPO_ROOT, "audios_for_pronunciation_test")


def _load_metadata(ref_dir):
    with open(os.path.join(ref_dir, "metadata.json"), "r", encoding="utf-8") as f:
        return json.load(f)


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def _demo_text_override(demo_dir, item_id, learner_id):
    if not demo_dir:
        return None
    path = os.path.join(demo_dir, item_id, f"{learner_id}.txt")
    return _read(path) if os.path.isfile(path) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audio-root", default=DEFAULT_AUDIO_ROOT)
    ap.add_argument("--ref-dir", default=DEFAULT_REF_DIR)
    ap.add_argument("--out-dir", default=os.path.join(REPO_ROOT, "outputs", "reports"))
    ap.add_argument("--asr", choices=["whisper", "none"], default="none")
    ap.add_argument("--demo-text-dir", default=None)
    ap.add_argument("--items", nargs="*", default=None)
    ap.add_argument("--limit-per-item", type=int, default=None)
    ap.add_argument("--verbose", action="store_true",
                     help="Print every pipeline stage for every sample (guru text, "
                          "ASR call + timing, normalization, script detection, "
                          "segmentation, alignment, rubrics, final score).")
    ap.add_argument("--no-audit-asr", dest="audit_asr", action="store_false", default=True,
                     help="Skip the end-of-run ASR audit summary table.")
    ap.add_argument("--write-stages", action="store_true",
                     help="For every learner scored, also write one JSON file per "
                          "pipeline stage to outputs/reports/<item>/<learner_id>_stages/ "
                          "(plus a combined 00_all_stages.json). Off by default since it "
                          "multiplies file count ~12x per learner over a full batch run.")
    args = ap.parse_args()

    metadata = _load_metadata(args.ref_dir)
    items = args.items or list(metadata.keys())

    asr = None
    if args.asr == "whisper":
        from src.asr.whisper_asr import WhisperASR
        asr = WhisperASR(verbose=args.verbose)

    learners_root = os.path.join(args.audio_root, "audios_learners")
    all_rows = []

    # audit_rows: one entry per learner file we attempted, regardless of
    # outcome, so the final table accounts for every single file.
    audit_rows = []

    for item_id in items:
        if item_id not in metadata:
            print(f"[skip] unknown item_id '{item_id}' (not in metadata.json)")
            continue
        meta = metadata[item_id]
        guru_text_path = os.path.join(args.ref_dir, f"{item_id}_unicode.txt")
        if not os.path.isfile(guru_text_path):
            print(f"[skip] {item_id}: missing reference text {guru_text_path}")
            continue
        guru_text = _read(guru_text_path)

        resp_dir = os.path.join(learners_root, meta["learner_dir"])
        if not os.path.isdir(resp_dir):
            print(f"[skip] {item_id}: learner responses dir not found: {resp_dir}")
            print(f"        (place your dataset at {args.audio_root}, or pass --audio-root)")
            continue

        audio_files = sorted(f for f in os.listdir(resp_dir) if not f.startswith("."))
        if args.limit_per_item:
            audio_files = audio_files[: args.limit_per_item]

        item_rows = []
        for fname in audio_files:
            learner_id = os.path.splitext(fname)[0]
            audio_path = os.path.join(resp_dir, fname)
            audio_bytes = os.path.getsize(audio_path) if os.path.isfile(audio_path) else None

            learner_text = _demo_text_override(args.demo_text_dir, item_id, learner_id)
            source = "demo_text_override" if learner_text is not None else None

            try:
                if learner_text is not None:
                    report = evaluate_sample(sample_id=f"{item_id}__{learner_id}",
                                              guru_text=guru_text, learner_text=learner_text,
                                              verbose=args.verbose)
                elif asr is not None:
                    report = evaluate_sample(sample_id=f"{item_id}__{learner_id}",
                                              guru_text=guru_text,
                                              learner_audio_path=audio_path, asr=asr,
                                              asr_lang=meta["whisper_lang"], verbose=args.verbose)
                    source = report.get("learner_text_source")
                else:
                    print(f"[skip] {item_id}/{fname}: no --asr backend and no demo text override")
                    audit_rows.append({"item_id": item_id, "learner_id": learner_id,
                                        "audio_bytes": audio_bytes, "outcome": "skipped_no_backend"})
                    continue
            except AudioPreflightError as e:
                print(f"[skip] {item_id}/{fname}: ASR preflight refused this audio file -- {e}")
                audit_rows.append({"item_id": item_id, "learner_id": learner_id,
                                    "audio_bytes": audio_bytes, "outcome": "preflight_rejected"})
                continue
            except Exception as e:
                print(f"[error] {item_id}/{fname}: {e}")
                audit_rows.append({"item_id": item_id, "learner_id": learner_id,
                                    "audio_bytes": audio_bytes, "outcome": f"error: {e}"})
                continue

            item_out_dir = os.path.join(args.out_dir, item_id)
            write_json(report, os.path.join(item_out_dir, f"{learner_id}.json"))
            write_markdown(report, os.path.join(item_out_dir, f"{learner_id}.md"))
            if args.write_stages:
                stages_dir = os.path.join(item_out_dir, f"{learner_id}_stages")
                write_stage_files(report, stages_dir)

            row = {
                "item_id": item_id, "language": meta["language"], "learner_id": learner_id,
                "overall_score": report["overall_score"], "grade": report["grade"],
                "rubric1_score": report["rubric1"]["score"],
                "rubric2_score": report["rubric2"]["score"],
                "rubric3_score": report["rubric3"]["score"],
            }
            item_rows.append(row)
            all_rows.append(row)
            audit_rows.append({
                "item_id": item_id, "learner_id": learner_id, "audio_bytes": audio_bytes,
                "outcome": "scored", "learner_text_source": source,
                "asr_elapsed_seconds": report.get("asr_elapsed_seconds"),
                "learner_text_len": len(report.get("learner_text", "")),
            })
            print(f"[ok] {item_id}/{learner_id}: {report['overall_score']}/100 ({report['grade']}) "
                  f"[source={source}]")

        if item_rows:
            item_out_dir = os.path.join(args.out_dir, item_id)
            with open(os.path.join(item_out_dir, "_item_summary.csv"), "w", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=list(item_rows[0].keys()))
                w.writeheader()
                w.writerows(item_rows)

    if all_rows:
        os.makedirs(args.out_dir, exist_ok=True)
        with open(os.path.join(args.out_dir, "overall_summary.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(all_rows[0].keys()))
            w.writeheader()
            w.writerows(all_rows)
        avg = sum(r["overall_score"] for r in all_rows) / len(all_rows)
        print(f"\nEvaluated {len(all_rows)} learner responses across {len(items)} item(s). "
              f"Average overall score: {avg:.1f}/100")
        print(f"Summary: {os.path.join(args.out_dir, 'overall_summary.csv')}")
    else:
        print("\nNo learner responses were evaluated. Check --audio-root / --asr / --demo-text-dir.")

    if args.audit_asr:
        _print_asr_audit(audit_rows, used_real_asr=(asr is not None))


def _print_asr_audit(audit_rows, used_real_asr: bool):
    """Prints a summary that answers, in one glance: for every learner
    audio file we touched, did it actually get transcribed by ASR, or was
    it skipped / rejected / scored from a demo-text override instead?"""
    print("\n" + "=" * 72)
    print("ASR AUDIT SUMMARY")
    print("=" * 72)
    if not audit_rows:
        print("No files were processed.")
        return

    from collections import Counter
    outcomes = Counter(r["outcome"] for r in audit_rows)
    for outcome, n in outcomes.items():
        print(f"  {outcome}: {n}")

    real_asr_rows = [r for r in audit_rows
                     if r.get("outcome") == "scored" and r.get("learner_text_source") == "asr"]
    demo_rows = [r for r in audit_rows
                 if r.get("outcome") == "scored" and r.get("learner_text_source") == "demo_text_override"]
    rejected = [r for r in audit_rows if r.get("outcome") == "preflight_rejected"]

    print(f"\n  Scored via REAL ASR on audio : {len(real_asr_rows)}")
    print(f"  Scored via demo-text override: {len(demo_rows)}")
    print(f"  Rejected by preflight (empty/too-small audio): {len(rejected)}")

    if real_asr_rows:
        avg_elapsed = sum(r["asr_elapsed_seconds"] or 0 for r in real_asr_rows) / len(real_asr_rows)
        avg_len = sum(r["learner_text_len"] for r in real_asr_rows) / len(real_asr_rows)
        print(f"\n  Real ASR calls: avg decode time {avg_elapsed:.2f}s, "
              f"avg transcript length {avg_len:.0f} chars.")
        print("  (Non-trivial, varying decode times + non-empty transcripts of plausible")
        print("   length are the evidence that audio was genuinely decoded, not stubbed.)")
    elif used_real_asr:
        print("\n  *** --asr whisper was requested but ZERO files were actually scored via")
        print("      real ASR. Every learner file either failed preflight (see below) or hit")
        print("      an error. Nothing in outputs/reports for this run reflects real audio. ***")

    if rejected:
        print(f"\n  Files rejected by the audio preflight check (< {MIN_PLAUSIBLE_AUDIO_BYTES} bytes "
              f"or missing) -- these produced NO score at all, so they won't silently show up")
        print("  as a suspiciously perfect/empty result:")
        for r in rejected[:20]:
            print(f"    - {r['item_id']}/{r['learner_id']}  ({r.get('audio_bytes')} bytes)")
        if len(rejected) > 20:
            print(f"    ... and {len(rejected) - 20} more")
    print("=" * 72)


if __name__ == "__main__":
    main()
