"""Plainly: a linter for prose that reads like a bot wrote it."""

from plainly.engine import FileReport, apply_fixes, lint_text
from plainly.findings import Finding, Fix, Severity

__version__ = "0.1.0"

__all__ = ["FileReport", "Finding", "Fix", "Severity", "__version__", "apply_fixes", "lint_text"]
