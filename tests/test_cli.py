"""The command: exit codes, formats, --fix, --stdin, baselines, subcommands."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from plainly.cli import main

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"
SLOP = (EXAMPLES / "slop.md").read_text("utf-8")


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "slop.md").write_text(SLOP, "utf-8")
    (tmp_path / "docs" / "clean.md").write_text((EXAMPLES / "clean.md").read_text("utf-8"), "utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "x.md").write_text("delve delve delve", "utf-8")
    (tmp_path / "plainly.toml").write_text("fail-under = 50\nallow = []\n", "utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def run(*args: str, capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    code = main(list(args))
    out = capsys.readouterr().out
    return code, out


def test_directory_lint_respects_excludes_and_fail_under(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run(".", "--no-color", capsys=capsys)
    assert code == 1  # slop scores under 50
    assert "docs/slop.md" in out and "docs/clean.md" in out
    assert "node_modules" not in out


def test_fail_on_never_and_fail_under_flag(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _ = run("docs/clean.md", "--fail-under", "0", "--no-color", capsys=capsys)
    assert code == 0
    code, _ = run("docs/clean.md", "--fail-on", "info", "--fail-under", "0", capsys=capsys)
    assert code == 1  # the one long-sentence info
    code, _ = run("docs/clean.md", "--fail-on", "never", "--fail-under", "0", capsys=capsys)
    assert code == 0


def test_json_and_sarif_outputs(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _, out = run("docs/slop.md", "--format", "json", "--fail-under", "0", capsys=capsys)
    data = json.loads(out)
    assert data["files"][0]["score"] < 20
    assert data["files"][0]["findings"][0]["rule"]
    _, out = run("docs/slop.md", "--format", "sarif", "--fail-under", "0", capsys=capsys)
    sarif = json.loads(out)
    assert sarif["version"] == "2.1.0"
    run_ = sarif["runs"][0]
    assert run_["tool"]["driver"]["name"] == "Plainly"
    assert run_["results"]
    rule_ids = {r["id"] for r in run_["tool"]["driver"]["rules"]}
    assert all(r["ruleId"] in rule_ids for r in run_["results"])
    fixes = [r for r in run_["results"] if "fixes" in r]
    assert fixes and fixes[0]["fixes"][0]["artifactChanges"][0]["replacements"]


def test_github_and_markdown_outputs(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _, out = run("docs/slop.md", "--format", "github", "--fail-under", "0", capsys=capsys)
    assert out.startswith("::warning file=docs/slop.md,line=1,col=3,")
    _, out = run("docs", "--format", "markdown", "--fail-under", "0", capsys=capsys)
    assert "| `docs/clean.md` |" in out and "Top findings" in out


def test_fix_writes_file_and_is_stable(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    before = (project / "docs" / "slop.md").read_text("utf-8")
    code, out = run("docs/slop.md", "--fix", "--fail-under", "0", "--no-color", capsys=capsys)
    after = (project / "docs" / "slop.md").read_text("utf-8")
    assert code == 0 and after != before and "fixed" in out
    assert "In conclusion" not in after and "in order to" not in after.lower()
    _code, out = run("docs/slop.md", "--fix", "--fail-under", "0", "--no-color", capsys=capsys)
    assert (project / "docs" / "slop.md").read_text("utf-8") == after


def test_diff_does_not_write(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    before = (project / "docs" / "slop.md").read_text("utf-8")
    code, out = run("docs/slop.md", "--diff", capsys=capsys)
    assert code == 0 and out.startswith("--- a/docs/slop.md")
    assert (project / "docs" / "slop.md").read_text("utf-8") == before


def test_stdin(project: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    import io

    monkeypatch.setattr(sys, "stdin", io.StringIO("It is important to note that we delve.\n"))
    code, out = run("--stdin", "--stdin-name", "PR.md", "--no-color", "--fail-under", "0", capsys=capsys)
    assert code == 0 and "PR.md" in out and "delve" in out
    monkeypatch.setattr(sys, "stdin", io.StringIO("It is important to note that we delve.\n"))
    _code, out = run("--stdin", "--fix", capsys=capsys)
    assert out == "We look.\n"


def test_baseline_flow(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run("docs", "--write-baseline", capsys=capsys)
    assert code == 0 and (project / ".plainly-baseline.json").is_file()
    code, out = run("docs", "--no-color", "--fail-under", "0", capsys=capsys)
    assert code == 0 and "0 findings" in out
    code, out = run("docs", "--no-baseline", "--quiet", "--no-color", "--fail-under", "0", capsys=capsys)
    assert "67 findings" in out or "findings" in out


def test_select_ignore_statistics(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _, out = run(
        "docs/slop.md",
        "--select",
        "padding",
        "--statistics",
        "--quiet",
        "--fail-under",
        "0",
        "--no-color",
        capsys=capsys,
    )
    assert "padding/" in out and "tells/" not in out


def test_subcommands(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, out = run("rules", capsys=capsys)
    assert code == 0 and "tells/vocabulary" in out and "rules," in out
    code, out = run("rules", "--format", "json", capsys=capsys)
    assert any(r["id"] == "tells/vocabulary" and r["examples"] for r in json.loads(out))
    code, out = run("explain", "tells/vocabulary", capsys=capsys)
    assert code == 0 and "before:" in out
    code, out = run("explain", "nope", capsys=capsys)
    assert code == 2
    os.remove(project / "plainly.toml")
    code, out = run("init", capsys=capsys)
    assert code == 0 and (project / "plainly.toml").is_file()
    code, _ = run("init", capsys=capsys)
    assert code == 2


def test_missing_path_and_bad_config(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["nope.md"]) == 2
    (project / "plainly.toml").write_text("fail-on = 'maybe'\n", "utf-8")
    assert main(["docs"]) == 2


def test_changed_files_via_git(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=project, check=True, capture_output=True)

    git("init", "-q")
    git("-c", "user.name=t", "-c", "user.email=t@t", "add", ".")
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "base")
    (project / "docs" / "clean.md").write_text("Fine.\n", "utf-8")
    (project / "docs" / "new.md").write_text("We delve.\n", "utf-8")
    git("add", ".")
    _code, out = run("--changed", "HEAD", "--no-color", "--fail-under", "0", capsys=capsys)
    assert "docs/clean.md" in out and "docs/new.md" in out and "slop.md" not in out


def test_module_entry_point() -> None:
    result = subprocess.run([sys.executable, "-m", "plainly", "--version"], capture_output=True, text=True)
    assert result.returncode == 0 and result.stdout.startswith("plainly ")
