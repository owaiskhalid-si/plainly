"""Output formats: pretty (terminal), github (workflow annotations), json, sarif, markdown."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Iterable

from plainly import __version__
from plainly.engine import FileReport
from plainly.findings import Finding, Severity
from plainly.rules import REGISTRY

FORMATS = ("pretty", "github", "json", "sarif", "markdown")


def render(fmt: str, reports: list[FileReport], *, color: bool | None = None, quiet: bool = False) -> str:
    if fmt == "pretty":
        return pretty(reports, color=_use_color(color), quiet=quiet)
    if fmt == "github":
        return github(reports)
    if fmt == "json":
        return json.dumps(
            {"version": __version__, "files": [r.to_dict() for r in reports], **totals(reports)}, indent=2
        )
    if fmt == "sarif":
        return json.dumps(sarif(reports), indent=2)
    if fmt == "markdown":
        return markdown(reports)
    raise ValueError(f"unknown format {fmt}")


def totals(reports: Iterable[FileReport]) -> dict[str, object]:
    reports = list(reports)
    words = sum(r.words for r in reports)
    findings = [f for r in reports if r.findings for f in r.findings]
    return {
        "fileCount": len(reports),
        "words": words,
        "findings": len(findings),
        "counts": {s.value: sum(1 for f in findings if f.severity is s) for s in Severity},
        "fixable": sum(1 for f in findings if f.fix is not None),
        "averageScore": round(sum(r.score * r.words for r in reports) / words) if words else 100,
    }


# ----- pretty ---------------------------------------------------------------------------


class _Paint:
    def __init__(self, on: bool) -> None:
        self.on = on

    def __call__(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.on else text


SEVERITY_STYLE = {Severity.ERROR: ("31", "error"), Severity.WARNING: ("33", "warning"), Severity.INFO: ("36", "info")}


def pretty(reports: list[FileReport], *, color: bool, quiet: bool) -> str:
    p = _Paint(color)
    lines: list[str] = []
    for r in reports:
        if not r.findings and quiet:
            continue
        heading = f"{p('1', r.path)}  {_score_label(p, r.score)} {r.verdict}, {r.words} words"
        if r.findings:
            heading += f", {len(r.findings)} finding{'s' if len(r.findings) != 1 else ''}"
            if r.fixable:
                heading += f" ({r.fixable} fixable)"
        if r.fixes_applied:
            heading += f", {r.fixes_applied} fixed"
        lines.append(heading)
        if quiet:
            continue
        for f in r.findings:
            code, label = SEVERITY_STYLE[f.severity]
            lines.append(
                f"  {p('2', f'{f.line}:{f.col}')}  {p(code, label):<{18 if color else 7}} {f.message}  {p('2', f.rule)}"
            )
            excerpt = _excerpt(r.source, f)
            if excerpt:
                src, underline = excerpt
                lines.append(f"       {p('2', '|')} {src}")
                lines.append(f"       {p('2', '|')} {p(code, underline)}")
            if f.suggestion:
                lines.append(f"       {p('32', '→')} {f.suggestion}")
        lines.append("")
    t = totals(reports)
    summary = f"{t['fileCount']} file{'s' if t['fileCount'] != 1 else ''}, {t['words']} words, {t['findings']} findings"
    counts = t["counts"]
    assert isinstance(counts, dict)
    parts = [
        f"{counts[s.value]} {s.value}{'s' if counts[s.value] != 1 and s is not Severity.INFO else ''}"
        for s in Severity
        if counts[s.value]
    ]
    if parts:
        summary += f" ({', '.join(parts)})"
    if t["fixable"]:
        summary += f", {t['fixable']} fixable with --fix"
    summary += f". Average score {t['averageScore']}."
    lines.append(p("1", summary))
    return "\n".join(lines)


def _score_label(p: _Paint, score: int) -> str:
    code = "32" if score >= 85 else "33" if score >= 65 else "31"
    return p(f"1;{code}", f"{score:>3}")


def _excerpt(source: str, f: Finding, width: int = 100) -> tuple[str, str] | None:
    if not source or f.line == 0:
        return None
    line_start = source.rfind("\n", 0, f.start) + 1
    line_end = source.find("\n", f.start)
    if line_end == -1:
        line_end = len(source)
    line = source[line_start:line_end].rstrip("\r")
    a = f.start - line_start
    b = min(f.end, line_end) - line_start
    if b <= a:
        b = a + 1
    # Window the line around the finding.
    left = max(0, a - 40) if len(line) > width else 0
    window = line[left : left + width]
    prefix = "…" if left > 0 else ""
    suffix = "…" if left + width < len(line) else ""
    shown = prefix + window.replace("\t", " ") + suffix
    caret_at = a - left + len(prefix)
    caret_len = max(1, min(b - a, len(shown) - caret_at))
    return shown, " " * caret_at + "^" * caret_len


def _use_color(color: bool | None) -> bool:
    if color is not None:
        return color
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return sys.stdout.isatty()


# ----- github ---------------------------------------------------------------------------


def github(reports: list[FileReport]) -> str:
    lines = []
    for r in reports:
        for f in r.findings:
            level = {"error": "error", "warning": "warning", "info": "notice"}[f.severity.value]
            msg = f.message + (f" {f.suggestion}." if f.suggestion else "")
            lines.append(
                f"::{level} file={r.path},line={f.line},col={f.col},endLine={f.end_line},endColumn={f.end_col},"
                f"title={_gh_escape(f.rule)}::{_gh_escape(msg)}"
            )
    return "\n".join(lines)


def _gh_escape(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A").replace(",", "%2C").replace(":", "%3A")


# ----- sarif ----------------------------------------------------------------------------


def sarif(reports: list[FileReport]) -> dict[str, object]:
    used = sorted({f.rule for r in reports for f in r.findings})
    rules = []
    index = {}
    for i, rule_id in enumerate(used):
        meta = REGISTRY.get(rule_id)
        index[rule_id] = i
        rules.append(
            {
                "id": rule_id,
                "name": meta.name if meta else rule_id,
                "shortDescription": {"text": meta.summary if meta else rule_id},
                "fullDescription": {"text": (meta.why or meta.summary) if meta else rule_id},
                "helpUri": "https://github.com/owaiskhalid-si/plainly#rules",
                "defaultConfiguration": {"level": _sarif_level(meta.severity) if meta else "warning"},
            }
        )
    results = []
    for r in reports:
        for f in r.findings:
            result: dict[str, object] = {
                "ruleId": f.rule,
                "ruleIndex": index[f.rule],
                "level": _sarif_level(f.severity),
                "message": {"text": f.message + (f" {f.suggestion}." if f.suggestion else "")},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": r.path.replace("\\", "/"), "uriBaseId": "%SRCROOT%"},
                            "region": {
                                "startLine": f.line,
                                "startColumn": f.col,
                                "endLine": f.end_line,
                                "endColumn": f.end_col,
                                "snippet": {"text": f.text},
                            },
                        }
                    }
                ],
            }
            if f.fix is not None:
                lines_before = r.source.count("\n", 0, f.fix.start) + 1
                col_before = f.fix.start - (r.source.rfind("\n", 0, f.fix.start) + 1) + 1
                lines_end = r.source.count("\n", 0, f.fix.end) + 1
                col_end = f.fix.end - (r.source.rfind("\n", 0, f.fix.end) + 1) + 1
                result["fixes"] = [
                    {
                        "description": {"text": f.suggestion or "Apply the fix"},
                        "artifactChanges": [
                            {
                                "artifactLocation": {"uri": r.path.replace("\\", "/"), "uriBaseId": "%SRCROOT%"},
                                "replacements": [
                                    {
                                        "deletedRegion": {
                                            "startLine": lines_before,
                                            "startColumn": col_before,
                                            "endLine": lines_end,
                                            "endColumn": col_end,
                                        },
                                        "insertedContent": {"text": f.fix.replacement},
                                    }
                                ],
                            }
                        ],
                    }
                ]
            results.append(result)
    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "Plainly",
                        "version": __version__,
                        "informationUri": "https://github.com/owaiskhalid-si/plainly",
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }


def _sarif_level(s: Severity) -> str:
    return {"error": "error", "warning": "warning", "info": "note"}[s.value]


# ----- markdown (for $GITHUB_STEP_SUMMARY and PR comments) -------------------------------


def markdown(reports: list[FileReport]) -> str:
    t = totals(reports)
    lines = [
        "## Plainly",
        "",
        f"**Average score {t['averageScore']}** across {t['fileCount']} file{'s' if t['fileCount'] != 1 else ''}, "
        f"{t['words']} words, {t['findings']} finding{'s' if t['findings'] != 1 else ''}"
        + (f" ({t['fixable']} fixable with `plainly --fix`)" if t["fixable"] else "")
        + ".",
        "",
        "| File | Score | Verdict | Words | Tells / 1k | Findings |",
        "|---|---:|---|---:|---:|---:|",
    ]
    for r in reports:
        cells = [
            f"`{r.path}`",
            f"{_badge(r.score)} {r.score}",
            r.verdict,
            str(r.words),
            f"{r.tells_per_thousand:.1f}",
            str(len(r.findings)),
        ]
        lines.append("| " + " | ".join(cells) + " |")
    worst = sorted(
        (f for r in reports for f in r.findings), key=lambda f: (-f.severity.rank, -f.weight, f.path, f.line)
    )[:15]
    if worst:
        lines += ["", "<details><summary>Top findings</summary>", "", "| Where | Rule | Finding |", "|---|---|---|"]
        for f in worst:
            msg = f.message.replace("|", "\\|")
            lines.append(f"| `{f.path}:{f.line}` | `{f.rule}` | {msg} |")
        lines += ["", "</details>"]
    return "\n".join(lines) + "\n"


def _badge(score: int) -> str:
    return "🟢" if score >= 85 else "🟡" if score >= 65 else "🔴"
