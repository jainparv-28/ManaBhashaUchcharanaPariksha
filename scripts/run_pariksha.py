#!/usr/bin/env python3
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.pipeline import evaluate_sample
from src.report_generator import write_json, write_markdown, write_stages_json, write_per_stage_files


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def main():
    ap = argparse.ArgumentParser(description="Run Uchcharana Pariksha on one sample.")
    ap.add_argument("--sample-id", required=True)
    ap.add_argument("--guru-text", help="Guru's reference text (Devanagari), inline")
    ap.add_argument("--guru-text-file", help="Path to file with guru's reference text")
    ap.add_argument("--learner-text", help="Learner's transcript, inline -- text-only mode")
    ap.add_argument("--learner-text-file", help="Path to file with learner's transcript")
    ap.add_argument("--learner-audio", help="Path to learner's audio file -- full ASR mode")
    ap.add_argument("--asr", choices=["whisper", "none"], default="none")
    ap.add_argument("--lang", default="sa", help="'sa' for Sanskrit shlokas, 'te' for Telugu padyams")
    ap.add_argument("--out-dir", default="outputs/reports")
    args = ap.parse_args()

    guru_text = args.guru_text or (_read(args.guru_text_file) if args.guru_text_file else None)
    if not guru_text:
        ap.error("Provide --guru-text or --guru-text-file")

    learner_text = args.learner_text or (_read(args.learner_text_file) if args.learner_text_file else None)

    asr = None
    if learner_text is None:
        if not args.learner_audio:
            ap.error("Provide --learner-text[-file] OR --learner-audio (+ --asr)")
        if args.asr == "whisper":
            from src.asr.whisper_asr import WhisperASR
            asr = WhisperASR()
        else:
            ap.error("--learner-audio requires --asr whisper (or supply --learner-text instead)")

    report = evaluate_sample(
        sample_id=args.sample_id,
        guru_text=guru_text,
        learner_text=learner_text,
        learner_audio_path=args.learner_audio,
        asr=asr,
        asr_lang=args.lang,
    )

    json_path = os.path.join(args.out_dir, f"{args.sample_id}.json")
    md_path = os.path.join(args.out_dir, f"{args.sample_id}.md")
    stages_path = os.path.join(args.out_dir, f"{args.sample_id}.stages.json")
    write_json(report, json_path)
    write_markdown(report, md_path)
    write_stages_json(report, stages_path)
    # Always write ONE json file per pipeline stage too, e.g.
    # outputs/reports/<sample-id>/asr.json, normalization.json,
    # script_detection.json, segmentation.json, alignment.json,
    # rubric1.json, rubric2.json, rubric3.json, scoring.json
    stage_dir = os.path.join(args.out_dir, args.sample_id)
    write_per_stage_files(report, args.out_dir, args.sample_id)

    print(f"Overall score: {report['overall_score']}/100 ({report['grade']})")
    if report.get("asr_flagged"):
        print(f"[FLAGGED] {report.get('asr_flag_reason')}")
    print(f"Report written to: {json_path}")
    print(f"Report written to: {md_path}")
    print(f"Combined stage JSON written to: {stages_path}")
    print(f"Per-stage JSON files written to: {stage_dir}/*.json")


if __name__ == "__main__":
    main()