"""The `plainly` command."""

from __future__ import annotations

import argparse
import difflib
import json
import subprocess
import sys
from pathlib import Path

from plainly import __version__
from plainly.baseline import BASELINE_NAME, apply_baseline, read_baseline, write_baseline
from plainly.config import CONFIG_TEMPLATE, Config, ConfigError, load_config
from plainly.engine import FileReport, active_rules, lint_file, lint_text
from plainly.files import changed_files, collect_files
from plainly.findings import Severity
from plainly.reporters import FORMATS, render
from plainly.rules import REGISTRY, Rule

SUBCOMMANDS = ("rules", "explain", "init")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to a legacy code page
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if args and args[0] in SUBCOMMANDS:
        return _subcommand(args)
    parser = _lint_parser()
    ns = parser.parse_args(args)
    try:
        return _lint(ns)
    except ConfigError as e:
        print(f"plainly: config error: {e}", file=sys.stderr)
        return 2
    except FileNotFoundError as e:
        print(f"plainly: not found: {e}", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as e:
        print(f"plainly: git failed: {e.stderr.strip() if e.stderr else e}", file=sys.stderr)
        return 2


def _lint_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="plainly",
        description="A linter for prose that reads like a bot wrote it.",
        epilog="Subcommands: plainly rules, plainly explain RULE, plainly init.",
    )
    p.add_argument("paths", nargs="*", help="files or folders (default: the config root, or the current folder)")
    p.add_argument("--fix", action="store_true", help="apply the safe fixes in place")
    p.add_argument("--diff", action="store_true", help="show the safe fixes as a diff without writing")
    p.add_argument("--format", choices=FORMATS, default="pretty", help="output format (default: pretty)")
    p.add_argument("--output", "-o", type=Path, help="write the report to a file instead of stdout")
    p.add_argument("--fail-under", type=int, metavar="N", help="exit 1 when any file scores below N (0–100)")
    p.add_argument("--fail-on", choices=("error", "warning", "info", "never"), help="exit 1 at this severity or above")
    p.add_argument("--select", metavar="RULES", help="only these rules or categories, comma-separated (or 'all')")
    p.add_argument("--ignore", metavar="RULES", help="skip these rules or categories, comma-separated")
    p.add_argument("--stdin", action="store_true", help="lint text from standard input")
    p.add_argument("--stdin-name", default="<stdin>", help="path to report for --stdin text")
    p.add_argument("--changed", metavar="REF", help="only files changed since REF (git diff --name-only REF)")
    p.add_argument(
        "--baseline",
        type=Path,
        metavar="FILE",
        help=f"hide findings listed in FILE (default: {BASELINE_NAME} if present)",
    )
    p.add_argument("--no-baseline", action="store_true", help="ignore a baseline file")
    p.add_argument("--write-baseline", action="store_true", help=f"record today's findings in {BASELINE_NAME} and exit")
    p.add_argument("--config", type=Path, help="config file (default: nearest plainly.toml or pyproject.toml)")
    p.add_argument("--color", action="store_true", help="force colour")
    p.add_argument("--no-color", action="store_true", help="no colour")
    p.add_argument("--quiet", "-q", action="store_true", help="one line per file, no findings")
    p.add_argument("--statistics", action="store_true", help="print a count per rule after the report")
    p.add_argument("--version", action="version", version=f"plainly {__version__}")
    return p


def _lint(ns: argparse.Namespace) -> int:
    config = load_config(ns.config)
    select = _split(ns.select)
    ignore = _split(ns.ignore)
    fix = bool(ns.fix or ns.diff)
    reports: list[FileReport] = []
    sources: dict[str, Path] = {}

    if ns.stdin:
        text = sys.stdin.read()
        reports.append(lint_text(text, ns.stdin_name, config, select=select, ignore=ignore, fix=fix))
    else:
        files = changed_files(ns.changed, config) if ns.changed else collect_files(ns.paths, config)
        if not files:
            print("plainly: no files to lint", file=sys.stderr)
            return 0
        for path in files:
            report = lint_file(path, config, select=select, ignore=ignore, fix=fix)
            reports.append(report)
            sources[report.path] = path

    if ns.write_baseline:
        target = ns.baseline or config.root / BASELINE_NAME
        n = write_baseline(reports, target)
        print(f"plainly: recorded {n} findings in {target}")
        return 0
    baseline_path = ns.baseline or (config.root / BASELINE_NAME)
    if not ns.no_baseline and baseline_path.is_file():
        hidden = apply_baseline(reports, read_baseline(baseline_path))
        if hidden and ns.format == "pretty":
            print(f"plainly: {hidden} findings hidden by {baseline_path.name}", file=sys.stderr)

    if ns.fix and not ns.stdin:
        for report in reports:
            if report.fixed_text is not None and report.fixes_applied:
                sources[report.path].write_text(report.fixed_text, "utf-8")
        # Report what is left after fixing.
        relinted = []
        for r in reports:
            after = lint_text(
                r.fixed_text if r.fixed_text is not None else r.source, r.path, config, select=select, ignore=ignore
            )
            after.fixes_applied = r.fixes_applied
            relinted.append(after)
        reports = relinted
    if ns.diff:
        for report in reports:
            if report.fixed_text is not None and report.fixed_text != report.source:
                sys.stdout.writelines(
                    difflib.unified_diff(
                        report.source.splitlines(keepends=True),
                        report.fixed_text.splitlines(keepends=True),
                        f"a/{report.path}",
                        f"b/{report.path}",
                    )
                )
        return 0
    if ns.fix and ns.stdin:
        sys.stdout.write(reports[0].fixed_text or reports[0].source)
        return 0

    color = True if ns.color else False if ns.no_color else None
    out = render(ns.format, reports, color=color, quiet=ns.quiet)
    if ns.output:
        ns.output.write_text(out + ("\n" if not out.endswith("\n") else ""), "utf-8")
        if ns.format != "pretty":
            print(f"plainly: wrote {ns.output}", file=sys.stderr)
    else:
        print(out)
    if ns.statistics:
        print(_statistics(reports))
    return _exit_code(reports, config, ns)


def _exit_code(reports: list[FileReport], config: Config, ns: argparse.Namespace) -> int:
    fail_under = ns.fail_under if ns.fail_under is not None else config.fail_under
    fail_on = ns.fail_on or config.fail_on
    failed = False
    for r in reports:
        if fail_under and r.score < fail_under:
            failed = True
        if fail_on != "never":
            threshold = Severity(fail_on).rank
            if any(f.severity.rank >= threshold for f in r.findings):
                failed = True
    return 1 if failed else 0


def _statistics(reports: list[FileReport]) -> str:
    counts: dict[str, int] = {}
    for r in reports:
        for f in r.findings:
            counts[f.rule] = counts.get(f.rule, 0) + 1
    rows = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return "\n".join(f"{n:>5}  {rule}" for rule, n in rows) or "no findings"


def _split(value: str | None) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()] if value else []


# ----- subcommands ------------------------------------------------------------------------


def _subcommand(args: list[str]) -> int:
    name, rest = args[0], args[1:]
    if name == "rules":
        p = argparse.ArgumentParser(prog="plainly rules", description="List every rule.")
        p.add_argument("--format", choices=("table", "json"), default="table")
        p.add_argument("--config", type=Path)
        ns = p.parse_args(rest)
        config = load_config(ns.config)
        on = {r.id for r in active_rules(config)}
        if ns.format == "json":
            print(json.dumps(rules_json(on), indent=2))
            return 0
        width = max(len(r.id) for r in REGISTRY.values())
        for r in REGISTRY.values():
            state = "on " if r.id in on else "off"
            flags = "fix" if r.fixable else "   "
            print(f"{r.id:<{width}}  {state}  {r.severity.value:<7}  {flags}  {r.summary}")
        print(f"\n{len(REGISTRY)} rules, {len(on)} on. `plainly explain RULE` shows examples and options.")
        return 0
    if name == "explain":
        p = argparse.ArgumentParser(prog="plainly explain", description="Explain a rule.")
        p.add_argument("rule")
        ns = p.parse_args(rest)
        found: Rule | None = REGISTRY.get(ns.rule)
        if found is None:
            matches = [x for x in REGISTRY if ns.rule in x]
            print(
                f"plainly: no rule {ns.rule!r}" + (f"; did you mean {', '.join(matches)}?" if matches else ""),
                file=sys.stderr,
            )
            return 2
        state = "on" if found.enabled else "off"
        fixable = "; fixable" if found.fixable else ""
        print(f"{found.id}  ({found.name}; {found.severity.value}; {state} by default{fixable})")
        print(f"\n{found.summary}")
        if found.why:
            print(f"\n{found.why}")
        if found.options:
            print("\nOptions:")
            for k, v in found.options.items():
                print(f"  {k} = {json.dumps(v)}")
        if found.examples:
            print("\nExamples:")
            for ex in found.examples:
                print(f"  before: {ex.before}")
                print(f"  after:  {ex.after}\n")
        return 0
    if name == "init":
        p = argparse.ArgumentParser(prog="plainly init", description="Write a plainly.toml in the current folder.")
        p.add_argument("--force", action="store_true")
        ns = p.parse_args(rest)
        target = Path("plainly.toml")
        if target.exists() and not ns.force:
            print("plainly: plainly.toml exists (use --force to overwrite)", file=sys.stderr)
            return 2
        target.write_text(CONFIG_TEMPLATE, "utf-8")
        print("plainly: wrote plainly.toml")
        return 0
    return 2


def rules_json(on: set[str]) -> list[dict[str, object]]:
    return [
        {
            "id": r.id,
            "name": r.name,
            "category": r.category,
            "summary": r.summary,
            "why": r.why,
            "severity": r.severity.value,
            "enabled": r.id in on,
            "fixable": r.fixable,
            "options": r.options,
            "examples": [{"before": e.before, "after": e.after} for e in r.examples],
        }
        for r in REGISTRY.values()
    ]
