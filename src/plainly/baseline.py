"""A baseline lets a project adopt Plainly without fixing every old page first: findings recorded in
the baseline are hidden, new ones are reported. Entries are keyed by rule, file and matched text,
so they survive line shifts."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from plainly.engine import FileReport, score_for, tells_rate

BASELINE_NAME = ".plainly-baseline.json"


def key_of(path: str, rule: str, text: str) -> str:
    return f"{path}|{rule}|{' '.join(text.split())}"


def write_baseline(reports: list[FileReport], path: Path) -> int:
    counts: Counter[str] = Counter()
    for report in reports:
        for f in report.findings:
            counts[key_of(report.path, f.rule, f.text)] += 1
    data = {"version": 1, "entries": dict(sorted(counts.items()))}
    path.write_text(json.dumps(data, indent=2) + "\n", "utf-8")
    return sum(counts.values())


def read_baseline(path: Path) -> Counter[str]:
    data = json.loads(path.read_text("utf-8"))
    entries = data.get("entries", {})
    return Counter({str(k): int(v) for k, v in entries.items()})


def apply_baseline(reports: list[FileReport], baseline: Counter[str]) -> int:
    """Drop findings present in the baseline. Returns how many were hidden."""
    remaining = Counter(baseline)
    hidden = 0
    for report in reports:
        kept = []
        for f in report.findings:
            k = key_of(report.path, f.rule, f.text)
            if remaining[k] > 0:
                remaining[k] -= 1
                hidden += 1
            else:
                kept.append(f)
        if len(kept) != len(report.findings):
            report.findings = kept
            report.score, report.verdict = score_for(kept, report.words)
            report.tells_per_thousand = tells_rate(kept, report.words)
    return hidden
