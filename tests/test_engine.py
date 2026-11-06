"""Scoring, fixes, dedupe, config and the baseline."""

from __future__ import annotations

from pathlib import Path

import pytest

from plainly.baseline import apply_baseline, read_baseline, write_baseline
from plainly.config import ConfigError, parse_config
from plainly.engine import active_rules, apply_fixes, lint_text
from plainly.findings import Severity

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def test_examples_score_as_expected() -> None:
    slop = lint_text((EXAMPLES / "slop.md").read_text("utf-8"), "slop.md")
    clean = lint_text((EXAMPLES / "clean.md").read_text("utf-8"), "clean.md")
    assert slop.score < 20, slop.score
    assert slop.verdict == "Reads generated"
    assert slop.tells_per_thousand > 50
    assert clean.score >= 90, [f.message for f in clean.findings]
    assert clean.verdict == "Plain"
    assert clean.tells_per_thousand == 0


def test_every_finding_points_at_its_text() -> None:
    src = (EXAMPLES / "slop.md").read_text("utf-8")
    report = lint_text(src, "slop.md")
    for f in report.findings:
        assert src[f.start : f.end] == f.text
        line = src.split("\n")[f.line - 1]
        assert line[f.col - 1 :].startswith(f.text.split("\n")[0])


def test_fixes_are_idempotent_and_do_not_overlap() -> None:
    src = (EXAMPLES / "slop.md").read_text("utf-8")
    first = lint_text(src, fix=True)
    assert first.fixed_text is not None and first.fixes_applied > 20
    second = lint_text(first.fixed_text, fix=True)
    assert second.fixes_applied == 0, [f.text for f in second.findings if f.fix]
    assert second.score > first.score


def test_apply_fixes_skips_overlaps() -> None:
    text = "aaa bbb ccc"
    r1 = lint_text(text)
    from plainly.findings import Finding, Fix

    f1 = Finding("x/a", Severity.INFO, "", 0, 7, fix=Fix(0, 7, "X"))
    f2 = Finding("x/b", Severity.INFO, "", 4, 11, fix=Fix(4, 11, "Y"))
    assert apply_fixes(text, [f1, f2]) == ("X ccc", 1)
    assert r1.findings == []


def test_nested_findings_are_deduped() -> None:
    report = lint_text("It lives in the realm of software.")
    assert [f.text for f in report.findings] == ["in the realm of"]


def test_directive_hides_findings() -> None:
    report = lint_text("<!-- plainly-disable-next-line -->\nWe delve in.\n\nWe delve again.\n")
    assert [f.line for f in report.findings] == [4]


def test_allow_list_from_config(tmp_path: Path) -> None:
    cfg = parse_config({"allow": ["robust"]}, tmp_path)
    report = lint_text("A robust and seamless tool.", config=cfg)
    assert [f.text for f in report.findings] == ["seamless"]


def test_config_enables_disables_and_overrides(tmp_path: Path) -> None:
    cfg = parse_config(
        {
            "enable": ["clarity/passive"],
            "disable": ["padding"],
            "rules": {"clarity/long-sentence": {"max-words": 5, "severity": "error"}},
        },
        tmp_path,
    )
    ids = {r.id for r in active_rules(cfg)}
    assert "clarity/passive" in ids
    assert not any(i.startswith("padding/") for i in ids)
    report = lint_text("This sentence has more than five words in it.", config=cfg)
    long = [f for f in report.findings if f.rule == "clarity/long-sentence"]
    assert long and long[0].severity is Severity.ERROR


def test_config_rejects_unknown_keys(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        parse_config({"includes": []}, tmp_path)
    with pytest.raises(ConfigError):
        parse_config({"fail-on": "sometimes"}, tmp_path)


def test_select_and_ignore() -> None:
    text = "We delve. In order to win."
    assert {f.rule for f in lint_text(text, select=["padding"]).findings} == {"padding/wordy"}
    assert {f.rule for f in lint_text(text, ignore=["tells"]).findings} == {"padding/wordy"}


def test_baseline_round_trip(tmp_path: Path) -> None:
    text = "We delve here. We delve there."
    reports = [lint_text(text, "a.md")]
    path = tmp_path / "base.json"
    assert write_baseline(reports, path) == 2
    later = [lint_text(text + " We delve again.", "a.md")]
    hidden = apply_baseline(later, read_baseline(path))
    assert hidden == 2
    assert len(later[0].findings) == 1
    assert later[0].score > 0


def test_empty_text_scores_100() -> None:
    report = lint_text("")
    assert report.score == 100 and report.findings == []
