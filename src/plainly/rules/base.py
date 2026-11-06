"""How a rule is declared and registered."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from plainly.document import Document
from plainly.findings import Finding, Fix, Severity
from plainly.lexicon import Term, compile_terms

Check = Callable[[Document, Mapping[str, Any]], Iterable[Finding]]


@dataclass(frozen=True)
class Example:
    before: str
    after: str


@dataclass(frozen=True)
class Rule:
    id: str
    name: str
    summary: str
    severity: Severity
    check: Check
    enabled: bool = True
    fixable: bool = False
    options: dict[str, Any] = field(default_factory=dict)
    examples: tuple[Example, ...] = ()
    why: str = ""

    @property
    def category(self) -> str:
        return self.id.split("/", 1)[0]


REGISTRY: dict[str, Rule] = {}


def rule(
    id: str,
    name: str,
    summary: str,
    severity: Severity,
    *,
    enabled: bool = True,
    fixable: bool = False,
    options: dict[str, Any] | None = None,
    examples: tuple[Example, ...] = (),
    why: str = "",
) -> Callable[[Check], Check]:
    def register(check: Check) -> Check:
        if id in REGISTRY:
            raise ValueError(f"rule {id} registered twice")
        REGISTRY[id] = Rule(id, name, summary, severity, check, enabled, fixable, dict(options or {}), examples, why)
        return check

    return register


# ----- helpers shared by rules --------------------------------------------------------------


def deletion_fix(doc: Document, start: int, end: int) -> Fix:
    """A fix that removes source[start:end] and the whitespace after it, and re-capitalises the
    next word when the removed phrase began a sentence."""
    source = doc.source
    cut_end = end
    while cut_end < len(source) and source[cut_end] in " \t":
        cut_end += 1
    if cut_end == end and start > 0 and source[start - 1] in " \t":
        # Nothing after; eat the space before instead ("...word very." -> "...word.").
        return Fix(start - 1, end, "")
    if doc.is_sentence_start(start) and cut_end < len(source) and source[cut_end].islower():
        return Fix(start, cut_end + 1, source[cut_end].upper())
    return Fix(start, cut_end, "")


def replacement_fix(doc: Document, start: int, end: int, replacement: str) -> Fix:
    """Swap a phrase for its plain equivalent, keeping the verb's ending ("empowers" -> "helps"),
    the capital letter, and the article before it ("a pivotal" -> "an important")."""
    if replacement == "":
        return deletion_fix(doc, start, end)
    matched = doc.source[start:end]
    replacement = inflect(replacement, matched)
    if matched[:1].isupper() and not replacement[:1].isupper():
        replacement = replacement[0].upper() + replacement[1:]
    before = doc.source[max(0, start - 3) : start].lower()
    vowel = replacement[:1].lower() in "aeiou"
    if before.endswith("an ") and not vowel:
        return Fix(start - 3, end, ("An " if doc.source[start - 3] == "A" else "an ")[:1] + " " + replacement)
    if before.endswith("a ") and not before.endswith("an ") and vowel:
        article = "An " if doc.source[start - 2] == "A" else "an "
        return Fix(start - 2, end, article + replacement)
    return Fix(start, end, replacement)


def inflect(replacement: str, matched: str) -> str:
    """Carry a single verb's ending over to its one-word replacement."""
    if " " in replacement or " " in matched.strip():
        return replacement
    m = matched.lower()
    base = replacement
    if m.endswith("ing"):
        return (base[:-1] if base.endswith("e") and not base.endswith("ee") else base) + "ing"
    if m.endswith("ed"):
        return base + "d" if base.endswith("e") else base + "ed"
    if m.endswith("s") and not m.endswith("ss"):
        return base + ("es" if base.endswith(("s", "sh", "ch", "x", "z")) else "s")
    return base


def match_terms(
    doc: Document,
    rule_id: str,
    terms: list[Term],
    opts: Mapping[str, Any],
    severity: Severity,
    message: Callable[[str, Term], str],
    *,
    kinds: tuple[str, ...] = ("heading", "paragraph", "item", "quote"),
    fix: bool = True,
    only_sentence_start: bool = False,
) -> list[Finding]:
    """Run a lexicon over the document's prose blocks."""
    allow = {a.lower() for a in opts.get("allow", ())}
    compiled = _compiled(rule_id, terms)
    out: list[Finding] = []
    for block in doc.blocks:
        if block.kind not in kinds:
            continue
        for pattern, term in compiled:
            for m in pattern.finditer(block.text):
                start, end = block.start + m.start(), block.start + m.end()
                text = doc.source[start:end]
                if text.lower() in allow or text.lower().strip(",.:!") in allow:
                    continue
                if is_mention(doc, start, end):
                    continue
                if only_sentence_start and not doc.is_sentence_start(start):
                    continue
                f = Finding(rule_id, severity, message(text, term), start, end, weight=term.weight)
                if term.replace is not None:
                    f.suggestion = f'Replace with "{term.replace}"' if term.replace else "Delete it"
                    if fix:
                        f.fix = replacement_fix(doc, start, end, term.replace)
                out.append(f)
    return out


OPENING_QUOTES = "\"“‘'"
CLOSING_QUOTES = "\"”’'"


def is_mention(doc: Document, start: int, end: int) -> bool:
    """True when the span is quoted on its own ("delve"): the writer is talking about the words,
    not using them."""
    s = doc.source
    if start == 0 or s[start - 1] not in OPENING_QUOTES:
        return False
    i = end
    while i < len(s) and s[i] in ".,!?:;":
        i += 1
    return i < len(s) and s[i] in CLOSING_QUOTES


_CACHE: dict[str, list[tuple[re.Pattern[str], Term]]] = {}


def _compiled(key: str, terms: list[Term]) -> list[tuple[re.Pattern[str], Term]]:
    if key not in _CACHE:
        _CACHE[key] = compile_terms(terms)
    return _CACHE[key]
