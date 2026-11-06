"""What a rule reports: a finding at an exact span of the source, maybe with a fix."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"

    @property
    def rank(self) -> int:
        return {"error": 3, "warning": 2, "info": 1}[self.value]

    @property
    def weight(self) -> int:
        """How much a finding of this severity costs in the score."""
        return self.rank


@dataclass(frozen=True)
class Fix:
    """Replace source[start:end] with `replacement`. Fixes never overlap when applied."""

    start: int
    end: int
    replacement: str


@dataclass
class Finding:
    rule: str
    severity: Severity
    message: str
    start: int
    end: int
    suggestion: str | None = None
    fix: Fix | None = None
    weight: int = 1
    # Filled in by the engine from the offsets.
    line: int = 0
    col: int = 0
    end_line: int = 0
    end_col: int = 0
    text: str = ""
    path: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def category(self) -> str:
        return self.rule.split("/", 1)[0]

    def to_dict(self) -> dict[str, object]:
        return {
            "rule": self.rule,
            "severity": self.severity.value,
            "message": self.message,
            "suggestion": self.suggestion,
            "path": self.path,
            "line": self.line,
            "col": self.col,
            "endLine": self.end_line,
            "endCol": self.end_col,
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "fix": None
            if self.fix is None
            else {"start": self.fix.start, "end": self.fix.end, "replacement": self.fix.replacement},
        }
