#!/usr/bin/env python3
"""
run_pariksha.py
----------------
CLI entry point for ONE learner's recitation of ONE item.

MODIFIED: added --verbose, which prints every pipeline stage as it runs
(see src/pipeline.py / src/stagelog.py), and prints an explicit one-line
confirmation of where learner_text actually came from (real ASR on the
given audio file vs. text supplied directly) using the new
learner_text_source / asr_* fields in the report dict.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.pipeline import evaluate_sample
from src.report_generator import write_json, write_markdown, write_stage_files


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read().strip()


def main():
    ap = argparse.ArgumentParser(description="Run Uchcharana Pariksha on one sample.")
    ap.add_argument("--sample-id", required=True)
    ap.add_argument("--guru-text")
    ap.add_argument("--guru-text-file")
    ap.add_argument("--learner-text")
    ap.add_argument("--learner-text-file")
    ap.add_argument("--learner-audio")
    ap.add_argument("--asr", choices=["whisper", "none"], default="none")
    ap.add_argument("--lang", default="sa")
    ap.add_argument("--out-dir", default="outputs/reports")
    ap.add_argument("--verbose", action="store_true",
                     help="Print every pipeline stage (guru text, ASR call + timing, "
                          "normalization, script detection, segmentation, alignment, "
                          "rubrics, final score) as it runs.")
    ap.add_argument("--write-stages", action="store_true",
                     help="Write one JSON file per pipeline stage to "
                          "<out-dir>/<sample-id>_stages/ (plus a combined "
                          "00_all_stages.json), in addition to the usual "
                          "<sample-id>.json / .md final report.")
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
            asr = WhisperASR(verbose=args.verbose)
        else:
            ap.error("--learner-audio requires --asr whisper (or supply --learner-text instead)")

    report = evaluate_sample(
        sample_id=args.sample_id,
        guru_text=guru_text,
        learner_text=learner_text,
        learner_audio_path=args.learner_audio,
        asr=asr,
        asr_lang=args.lang,
        verbose=args.verbose,
    )

    json_path = os.path.join(args.out_dir, f"{args.sample_id}.json")
    md_path = os.path.join(args.out_dir, f"{args.sample_id}.md")
    write_json(report, json_path)
    write_markdown(report, md_path)

    print(f"Overall score: {report['overall_score']}/100 ({report['grade']})")
    print(f"Report written to: {json_path}")
    print(f"Report written to: {md_path}")

    if args.write_stages:
        stages_dir = os.path.join(args.out_dir, f"{args.sample_id}_stages")
        paths = write_stage_files(report, stages_dir)
        print(f"Stage-by-stage JSON files ({len(paths)}) written to: {stages_dir}/")
        for p in paths:
            print(f"    {p}")

    # Explicit, hard-to-miss confirmation of where the scored text came from.
    if report["learner_text_source"] == "asr":
        print(f"\n[ASR CONFIRMED] learner_text was produced by {report['asr_backend']} "
              f"transcribing {report['asr_audio_path']} "
              f"({report['asr_audio_bytes']} bytes, {report['asr_elapsed_seconds']}s decode time).")
    else:
        print("\n[NOTE] learner_text was supplied directly as text -- no ASR was run "
              "for this sample.")


if __name__ == "__main__":
    main()
