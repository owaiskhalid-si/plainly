"""Configuration from `plainly.toml` or `[tool.plainly]` in `pyproject.toml`."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_INCLUDE = ["**/*.md", "**/*.mdx", "**/*.markdown", "**/*.txt"]
DEFAULT_EXCLUDE = [
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "env",
    "dist",
    "build",
    "site-packages",
    "__pycache__",
    ".next",
    ".cache",
    "vendor",
    "CHANGELOG.md",
    "CHANGELOG",
    "LICENSE.md",
    "LICENSE.txt",
    "LICENSE",
    "CODE_OF_CONDUCT.md",
    "requirements.txt",
    "robots.txt",
]
FAIL_ON = ("error", "warning", "info", "never")

CONFIG_TEMPLATE = """# Plainly: a linter for prose that reads like a bot wrote it.
# Every key is optional. Run `plainly rules` to see every rule and its options.

# Files to lint when you pass a directory (or nothing). Patterns are relative to this file.
include = ["**/*.md", "**/*.mdx", "**/*.txt"]
exclude = ["CHANGELOG.md", "node_modules", "vendor"]

# Exit 1 when a file scores below this (0 = never).
fail-under = 60
# Exit 1 when any finding is at or above this severity: "error", "warning", "info" or "never".
fail-on = "error"

# Words your project uses on purpose. Matched case-insensitively.
allow = []

# Rules or whole categories to switch on or off. Categories: tells, padding, structure, clarity.
enable = []
disable = []

# Per-rule options and severity overrides.
[rules."clarity/long-sentence"]
max-words = 35

[rules."tells/em-dash"]
per-thousand = 4
"""


@dataclass
class Config:
    root: Path
    include: list[str] = field(default_factory=lambda: list(DEFAULT_INCLUDE))
    exclude: list[str] = field(default_factory=lambda: list(DEFAULT_EXCLUDE))
    fail_under: int = 0
    fail_on: str = "error"
    allow: list[str] = field(default_factory=list)
    enable: list[str] = field(default_factory=list)
    disable: list[str] = field(default_factory=list)
    rules: dict[str, dict[str, Any]] = field(default_factory=dict)
    source: Path | None = None


class ConfigError(ValueError):
    pass


def find_config(start: Path) -> Path | None:
    """Walk up from `start` for plainly.toml, or a pyproject.toml with a [tool.plainly] table."""
    for folder in [start, *start.parents]:
        candidate = folder / "plainly.toml"
        if candidate.is_file():
            return candidate
        pyproject = folder / "pyproject.toml"
        if pyproject.is_file():
            try:
                data = tomllib.loads(pyproject.read_text("utf-8"))
            except tomllib.TOMLDecodeError:
                continue
            if "plainly" in data.get("tool", {}):
                return pyproject
    return None


def load_config(explicit: Path | None = None, start: Path | None = None) -> Config:
    path = explicit or find_config((start or Path.cwd()).resolve())
    if path is None:
        return Config(root=(start or Path.cwd()).resolve())
    try:
        data = tomllib.loads(path.read_text("utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{path}: {e}") from e
    table = data.get("tool", {}).get("plainly", data) if path.name == "pyproject.toml" else data
    return parse_config(table, path.parent.resolve(), path)


def parse_config(table: dict[str, Any], root: Path, source: Path | None = None) -> Config:
    cfg = Config(root=root, source=source)
    known = {
        "include",
        "exclude",
        "fail-under",
        "fail_under",
        "fail-on",
        "fail_on",
        "allow",
        "enable",
        "disable",
        "rules",
    }
    for key in table:
        if key not in known:
            raise ConfigError(f"unknown config key: {key}")
    cfg.include = _strings(table.get("include"), "include") or cfg.include
    cfg.exclude = list(DEFAULT_EXCLUDE) + _strings(table.get("exclude"), "exclude")
    cfg.fail_under = int(table.get("fail-under", table.get("fail_under", 0)))
    cfg.fail_on = str(table.get("fail-on", table.get("fail_on", "error")))
    if cfg.fail_on not in FAIL_ON:
        raise ConfigError(f"fail-on must be one of {', '.join(FAIL_ON)}")
    if not 0 <= cfg.fail_under <= 100:
        raise ConfigError("fail-under must be between 0 and 100")
    cfg.allow = _strings(table.get("allow"), "allow")
    cfg.enable = _strings(table.get("enable"), "enable")
    cfg.disable = _strings(table.get("disable"), "disable")
    rules = table.get("rules", {})
    if not isinstance(rules, dict):
        raise ConfigError("rules must be a table")
    for rule_id, options in rules.items():
        if not isinstance(options, dict):
            raise ConfigError(f"rules.{rule_id} must be a table")
        cfg.rules[str(rule_id)] = dict(options)
    return cfg


def _strings(value: Any, key: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{key} must be a list of strings")
    return list(value)
