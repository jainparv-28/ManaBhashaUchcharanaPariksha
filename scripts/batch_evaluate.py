#!/usr/bin/env python3
import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.pipeline import evaluate_sample
from src.report_generator import write_json, write_markdown, write_stages_json, write_per_stage_files

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
    args = ap.parse_args()

    metadata = _load_metadata(args.ref_dir)
    items = args.items or list(metadata.keys())

    asr = None
    if args.asr == "whisper":
        from src.asr.whisper_asr import WhisperASR
        asr = WhisperASR()

    learners_root = os.path.join(args.audio_root, "audios_learners")
    all_rows = []
    flagged_rows = []

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
            continue

        audio_files = sorted(f for f in os.listdir(resp_dir) if not f.startswith("."))
        if args.limit_per_item:
            audio_files = audio_files[: args.limit_per_item]

        item_rows = []
        for fname in audio_files:
            learner_id = os.path.splitext(fname)[0]
            audio_path = os.path.join(resp_dir, fname)

            learner_text = _demo_text_override(args.demo_text_dir, item_id, learner_id)
            try:
                if learner_text is not None:
                    report = evaluate_sample(sample_id=f"{item_id}__{learner_id}",
                                              guru_text=guru_text, learner_text=learner_text)
                elif asr is not None:
                    report = evaluate_sample(sample_id=f"{item_id}__{learner_id}",
                                              guru_text=guru_text,
                                              learner_audio_path=audio_path, asr=asr,
                                              asr_lang=meta["whisper_lang"])
                else:
                    print(f"[skip] {item_id}/{fname}: no --asr backend and no demo text override")
                    continue
            except Exception as e:
                print(f"[error] {item_id}/{fname}: {e}")
                continue

            item_out_dir = os.path.join(args.out_dir, item_id)
            write_json(report, os.path.join(item_out_dir, f"{learner_id}.json"))
            write_markdown(report, os.path.join(item_out_dir, f"{learner_id}.md"))
            write_stages_json(report, os.path.join(item_out_dir, f"{learner_id}.stages.json"))
            # Always write ONE json file per pipeline stage too, e.g.
            # outputs/reports/<item_id>/<learner_id>/asr.json,
            # normalization.json, script_detection.json, segmentation.json,
            # alignment.json, rubric1.json, rubric2.json, rubric3.json,
            # scoring.json -- so each stage can be inspected independently.
            write_per_stage_files(report, item_out_dir, learner_id)

            row = {
                "item_id": item_id, "language": meta["language"], "learner_id": learner_id,
                "overall_score": report["overall_score"], "grade": report["grade"],
                "rubric1_score": report["rubric1"]["score"],
                "rubric2_score": report["rubric2"]["score"],
                "rubric3_score": report["rubric3"]["score"],
                "asr_flagged": report.get("asr_flagged", False),
                "asr_flag_reason": report.get("asr_flag_reason") or "",
            }
            item_rows.append(row)
            all_rows.append(row)
            if row["asr_flagged"]:
                flagged_rows.append(row)
            flag_note = "  [FLAGGED]" if row["asr_flagged"] else ""
            print(f"[ok] {item_id}/{learner_id}: {report['overall_score']}/100 ({report['grade']}){flag_note}")

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
        if flagged_rows:
            print(f"\n[ATTENTION] {len(flagged_rows)} response(s) were flagged as possibly-unreliable "
                  f"ASR transcripts (e.g. suspected prompt echo) -- their scores may not reflect real "
                  f"pronunciation. Review these learner_ids: "
                  + ", ".join(f"{r['item_id']}/{r['learner_id']}" for r in flagged_rows))
    else:
        print("\nNo learner responses were evaluated. Check --audio-root / --asr / --demo-text-dir.")


if __name__ == "__main__":
    main()