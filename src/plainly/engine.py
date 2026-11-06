"""Run the rules over a text and score it."""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from plainly.config import Config
from plainly.document import Document, parse
from plainly.findings import Finding, Severity
from plainly.rules import REGISTRY, Rule

VERDICTS = ((85, "Plain"), (65, "A few tells"), (40, "Padded"), (0, "Reads generated"))
TELL_RULES = ("tells/", "padding/throat-clearing", "structure/sign-off", "structure/bold-lead-bullets")


@dataclass
class FileReport:
    path: str
    findings: list[Finding]
    words: int
    score: int
    verdict: str
    tells_per_thousand: float
    source: str = field(default="", repr=False)
    fixed_text: str | None = field(default=None, repr=False)
    fixes_applied: int = 0

    def count(self, severity: Severity) -> int:
        return sum(1 for f in self.findings if f.severity is severity)

    @property
    def fixable(self) -> int:
        return sum(1 for f in self.findings if f.fix is not None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "words": self.words,
            "score": self.score,
            "verdict": self.verdict,
            "tellsPerThousand": round(self.tells_per_thousand, 1),
            "counts": {s.value: self.count(s) for s in Severity},
            "fixable": self.fixable,
            "fixesApplied": self.fixes_applied,
            "findings": [f.to_dict() for f in self.findings],
        }


def active_rules(
    config: Config | None = None,
    select: Iterable[str] | None = None,
    ignore: Iterable[str] | None = None,
) -> list[Rule]:
    """Rules that run, after config enable/disable and the command line's select/ignore."""
    enable = set(config.enable) if config else set()
    disable = set(config.disable) if config else set()
    selected = set(select or ())
    ignored = set(ignore or ())
    out = []
    for r in REGISTRY.values():
        names = {r.id, r.category, "all"}
        on = r.enabled or bool(names & enable)
        if names & disable:
            on = False
        if selected:
            on = bool(names & selected)
        if names & ignored:
            on = False
        if on:
            out.append(r)
    return out


def options_for(rule: Rule, config: Config | None) -> dict[str, Any]:
    opts = dict(rule.options)
    if config:
        opts.update(config.rules.get(rule.id, {}))
        if "allow" in opts or rule.fixable or rule.category in ("tells", "padding", "clarity", "structure"):
            opts["allow"] = list(opts.get("allow", [])) + list(config.allow)
    return opts


def lint_text(
    text: str,
    path: str = "<stdin>",
    config: Config | None = None,
    *,
    select: Iterable[str] | None = None,
    ignore: Iterable[str] | None = None,
    fix: bool = False,
) -> FileReport:
    doc = parse(text)
    findings: list[Finding] = []
    for r in active_rules(config, select, ignore):
        opts = options_for(r, config)
        severity = _severity_override(opts.get("severity"), r.severity)
        for f in r.check(doc, opts):
            if doc.is_disabled(f.rule, f.start):
                continue
            f.severity = severity if opts.get("severity") else f.severity
            _place(doc, f, path)
            findings.append(f)
    findings = dedupe(findings)
    words = doc.word_count
    score, verdict = score_for(findings, words)
    report = FileReport(
        path=path,
        findings=findings,
        words=words,
        score=score,
        verdict=verdict,
        tells_per_thousand=tells_rate(findings, words),
        source=text,
    )
    if fix:
        report.fixed_text, report.fixes_applied = apply_fixes(text, findings)
    return report


def lint_file(
    path: Path,
    config: Config | None = None,
    *,
    select: Iterable[str] | None = None,
    ignore: Iterable[str] | None = None,
    fix: bool = False,
    display: str | None = None,
) -> FileReport:
    text = path.read_text("utf-8")
    return lint_text(text, display or _display(path, config), config, select=select, ignore=ignore, fix=fix)


def dedupe(findings: list[Finding]) -> list[Finding]:
    """Drop a finding whose span sits inside another finding's span: "realm" inside "in the realm of".
    Of two equal spans, the one with a fix wins, then the more severe one. Document-level findings
    (whole blocks) do not swallow the findings inside them."""
    ordered = sorted(findings, key=lambda f: (f.start, -(f.end - f.start), f.fix is None, -f.severity.rank, f.rule))
    kept: list[Finding] = []
    for f in ordered:
        swallowed = False
        for k in kept:
            if (
                k.start <= f.start
                and f.end <= k.end
                and (k.end - k.start) <= 80
                and (k.start, k.end) != (f.start, f.end)
            ):
                swallowed = True
                break
            if (k.start, k.end) == (f.start, f.end) and k.rule != f.rule and (k.end - k.start) <= 80:
                swallowed = True
                break
        if not swallowed:
            kept.append(f)
    kept.sort(key=lambda f: (f.start, f.end, f.rule))
    return kept


def apply_fixes(text: str, findings: Iterable[Finding]) -> tuple[str, int]:
    """Apply every non-overlapping fix, last to first so offsets stay valid."""
    fixes = sorted((f.fix for f in findings if f.fix is not None), key=lambda x: (x.start, x.end))
    chosen = []
    last_end = -1
    for fx in fixes:
        if fx.start < last_end:
            continue
        chosen.append(fx)
        last_end = fx.end
    out = text
    for fx in reversed(chosen):
        out = out[: fx.start] + fx.replacement + out[fx.end :]
    return out, len(chosen)


def score_for(findings: list[Finding], words: int) -> tuple[int, str]:
    """0–100. Penalty per hundred words, weighted by severity and by how strong a tell the finding is.
    The curve is tuned so one tell per hundred words scores in the 80s, three in the 50s, and a page
    where every sentence has one lands under 20."""
    if words == 0:
        return 100, VERDICTS[0][1]
    penalty = sum(f.severity.weight * f.weight for f in findings)
    density = penalty / max(words, 80) * 100
    score = round(100 / (1 + math.pow(density / 9, 1.3)))
    score = max(0, min(100, score))
    verdict = next(v for threshold, v in VERDICTS if score >= threshold)
    return score, verdict


def tells_rate(findings: list[Finding], words: int) -> float:
    if words == 0:
        return 0.0
    n = sum(1 for f in findings if f.rule.startswith(TELL_RULES))
    return n / words * 1000


def _severity_override(value: Any, default: Severity) -> Severity:
    if value is None:
        return default
    try:
        return Severity(str(value))
    except ValueError as e:
        raise ValueError(f"unknown severity {value!r}; use error, warning or info") from e


def _place(doc: Document, f: Finding, path: str) -> None:
    f.line, f.col = doc.position(f.start)
    f.end_line, f.end_col = doc.position(max(f.end, f.start))
    f.text = doc.source[f.start : f.end]
    f.path = path


def _display(path: Path, config: Config | None) -> str:
    try:
        return path.resolve().relative_to(config.root).as_posix() if config else str(path)
    except ValueError:
        return str(path)
