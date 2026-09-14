"""
report_generator.py
--------------------
Turns a pipeline report dict into:
  (a) a JSON file for LMS integration (full report, including `stages`)
  (b) a human-readable Markdown report
  (c) a SEPARATE per-stage JSON file (write_stages_json) for anyone who
      wants to inspect/audit just one step of the workflow (ASR output,
      normalization, segmentation, alignment, each rubric, final scoring)
      without parsing the full report.
"""

from __future__ import annotations
import json
import os


def write_json(report: dict, out_path: str):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


def write_stages_json(report: dict, out_path: str):
    """Write just the stage-by-stage breakdown (report['stages']) to its
    own JSON file, keyed by stage name, so each stage of the workflow --
    asr, normalization, script_detection, segmentation, alignment,
    rubric1, rubric2, rubric3, scoring -- can be inspected independently."""
    stages = report.get("stages", {})
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"sample_id": report.get("sample_id"), "stages": stages}, f,
                   ensure_ascii=False, indent=2)


def write_per_stage_files(report: dict, out_dir: str, sample_id: str):
    """Write ONE json file per stage, e.g. outputs/reports/<item>/<id>/asr.json,
    .../normalization.json, etc. -- useful when different downstream tools
    each only care about a single stage."""
    stages = report.get("stages", {})
    stage_dir = os.path.join(out_dir, sample_id)
    os.makedirs(stage_dir, exist_ok=True)
    for stage_name, stage_data in stages.items():
        with open(os.path.join(stage_dir, f"{stage_name}.json"), "w", encoding="utf-8") as f:
            json.dump(stage_data, f, ensure_ascii=False, indent=2)


def to_markdown(report: dict) -> str:
    lines = []
    lines.append(f"# Uchcharana Pariksha Report -- {report['sample_id']}\n")
    lines.append(f"**Overall score:** {report['overall_score']} / 100  ")
    lines.append(f"**Grade:** {report['grade']}\n")
    lines.append(f"**Guru text:** {report['guru_text']}  ")
    lines.append(f"**Learner text (ASR / provided):** {report['learner_text']}\n")
    if report.get("used_transliteration_fallback"):
        lines.append("> ⚠️ **Note:** ASR returned romanized text for this recording; it was "
                      "auto-transliterated into native script before scoring. Treat this "
                      "report as lower-confidence -- see RUNNING.md troubleshooting.\n")
    if report.get("asr_flagged"):
        lines.append(f"> 🚩 **ASR quality flag:** {report.get('asr_flag_reason')} -- "
                      f"please spot-check this recording manually rather than trusting the "
                      f"score below at face value.\n")

    lines.append("## Akshara-by-akshara comparison\n")
    lines.append("| Guru | Learner | Result |")
    lines.append("|---|---|---|")
    for row in report["alignment_preview"]:
        mark = "OK" if row["tag"] == "match" else f"**{row['tag']}**"
        lines.append(f"| {row['guru']} | {row['learner']} | {mark} |")
    lines.append("")

    lines.append("## Error time intervals (learner audio)\n")
    if not report.get("timing_available"):
        lines.append("_Timing unavailable for this sample (text-only mode, or the ASR "
                      "backend didn't return word timestamps)._\n")
    elif not report.get("timed_errors"):
        lines.append("_No errors -- nothing to time._\n")
    else:
        lines.append("| Type | Guru | Learner | Start | End | Note |")
        lines.append("|---|---|---|---|---|---|")
        for e in report["timed_errors"]:
            start = f"{e['start']:.2f}s" if e["start"] is not None else "?"
            end = f"{e['end']:.2f}s" if e["end"] is not None else "?"
            approx = " (approx.)" if e.get("approximate") else ""
            lines.append(f"| {e['type']} | {e['guru_akshara'] or '-'} | {e['learner_akshara'] or '-'} "
                          f"| {start}{approx} | {end}{approx} | {e['note']} |")
        lines.append("")

    for key in ("rubric1", "rubric2", "rubric3"):
        rb = report[key]
        lines.append(f"## {rb['name']} -- {rb['score']}/100\n")
        for fb in rb["feedback"]:
            lines.append(f"- {fb}")
        if rb["errors"]:
            lines.append("\n<details><summary>Error detail</summary>\n")
            for e in rb["errors"]:
                lines.append(f"- {e}")
            lines.append("\n</details>")
        lines.append("")

    lines.append(f"## Tune / intonation note\n\n{report['tune_note']}\n")
    return "\n".join(lines)


def write_markdown(report: dict, out_path: str):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(to_markdown(report))