from __future__ import annotations
import json
import os


def write_json(report: dict, out_path: str):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


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

    lines.append("## Akshara-by-akshara comparison\n")
    lines.append("| Guru | Learner | Result |")
    lines.append("|---|---|---|")
    for row in report["alignment_preview"]:
        mark = "OK" if row["tag"] == "match" else f"**{row['tag']}**"
        lines.append(f"| {row['guru']} | {row['learner']} | {mark} |")
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


def write_stage_files(report: dict, out_dir: str) -> list:
    """Writes ONE JSON file per pipeline stage (guru text received, ASR
    preflight, ASR transcribe, normalize, script detect, romanization
    fallback check, segmentation, alignment, rubric1, rubric2, rubric3,
    done) into out_dir/, plus a single 00_all_stages.json with the full
    trace in one file. Requires report["pipeline_trace"] to be present,
    i.e. the sample must have been run through pipeline.evaluate_sample()
    (any verbose setting -- the full data is captured either way).

    Returns the list of file paths written, in stage order.
    """
    trace = report.get("pipeline_trace")
    if not trace:
        raise ValueError(
            "report has no 'pipeline_trace' -- re-run evaluate_sample() from "
            "the current pipeline.py (write_stage_files needs the per-stage "
            "trace that evaluate_sample() attaches to every report)."
        )

    os.makedirs(out_dir, exist_ok=True)
    written = []

    combined_path = os.path.join(out_dir, "00_all_stages.json")
    with open(combined_path, "w", encoding="utf-8") as f:
        json.dump(trace, f, ensure_ascii=False, indent=2)
    written.append(combined_path)

    for entry in trace:
        seq = entry.get("seq", 0)
        stage_name = entry.get("stage", "unknown").lower().replace(" ", "_")
        fname = f"{seq:02d}_{stage_name}.json"
        fpath = os.path.join(out_dir, fname)
        with open(fpath, "w", encoding="utf-8") as f:
            json.dump(entry, f, ensure_ascii=False, indent=2)
        written.append(fpath)

    return written
