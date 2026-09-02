"""
stagelog.py
-----------
Tiny utility for printing (and recording) a numbered, staged trace of what
the pipeline is actually doing, sample by sample.

Each stage carries TWO layers of information:
  - console fields (detail + short kwargs): what gets printed when
    verbose=True -- kept short/truncated so the terminal stays readable.
  - `data`: the FULL, untruncated, JSON-serializable payload for that
    stage (e.g. every akshara, the entire alignment, full rubric error
    lists) -- always captured regardless of verbose, because this is what
    gets written to outputs/reports/<sample>/stages/NN_<stage>.json by
    report_generator.write_stage_files(). Nothing is dropped here even
    though the console view is abbreviated.

`trace` (list of stage dicts, each with its full `data`) is returned to
the caller and embedded in the report JSON as report["pipeline_trace"];
report_generator.write_stage_files() additionally explodes it into one
JSON file per stage.
"""

from __future__ import annotations
import time
from typing import Any, Dict, List, Optional


class StageLog:
    def __init__(self, sample_id: str, verbose: bool = False):
        self.sample_id = sample_id
        self.verbose = verbose
        self.trace: List[Dict[str, Any]] = []
        self._t0 = time.time()
        self._seq = 0

    def stage(self, name: str, detail: str = "", data: Optional[dict] = None, **console_fields):
        self._seq += 1
        elapsed = round(time.time() - self._t0, 3)
        entry = {
            "seq": self._seq,
            "stage": name,
            "t+": elapsed,
            "detail": detail,
            "summary": console_fields,   # short fields, safe to print
            "data": data or {},           # full, untruncated payload for JSON export
        }
        self.trace.append(entry)
        if self.verbose:
            print(f"[{self.sample_id}] (t+{elapsed:>6.3f}s) [{self._seq:02d}] {name}: {detail}")
            for k, v in console_fields.items():
                print(f"    {k} = {v}")
        return entry

    def warn(self, message: str, data: Optional[dict] = None, **fields):
        self.stage("WARNING", message, data=data, level="warning", **fields)
        if not self.verbose:
            print(f"[{self.sample_id}] WARNING: {message}" +
                  (f" ({fields})" if fields else ""))
