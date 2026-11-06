"""Plain-English rules: jargon, passives, long sentences, nouns that used to be verbs."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from plainly import lexicon
from plainly.document import Document
from plainly.findings import Finding, Fix, Severity
from plainly.rules.base import Example, match_terms, rule


@rule(
    "clarity/jargon",
    "Business jargon",
    "'Paradigm shift', 'low-hanging fruit', 'move the needle', 'going forward', 'thought leader'.",
    Severity.WARNING,
    fixable=True,
    examples=(
        Example(
            "Going forward, we'll circle back on the low-hanging fruit.", "From now on, we'll start with the easy wins."
        ),
    ),
    why="Jargon is a way of sounding like the room instead of saying something to it.",
)
def jargon(doc: Document, opts: Mapping[str, Any]) -> list[Finding]:
    return match_terms(
        doc,
        "clarity/jargon",
        lexicon.JARGON,
        opts,
        Severity.WARNING,
        lambda text, term: f'"{text}": {term.note}.',
    )


PASSIVE = re.compile(
    r"(?<![\w-])(?P<aux>is|are|was|were|be|been|being|get|gets|got|getting)\s+(?:(?:not|also|often|usually|always|never|still|then|now|already|being)\s+)?(?P<part>\w+)(?![\w-])",
    re.IGNORECASE,
)


@rule(
    "clarity/passive",
    "Passive voice",
    "'The file is read by the parser' where 'The parser reads the file' would do. Off by default.",
    Severity.INFO,
    enabled=False,
    options={"max-per-hundred-words": 0},
    examples=(
        Example(
            "The config is loaded by the CLI before the rules are run.",
            "The CLI loads the config before it runs the rules.",
        ),
    ),
    why=(
        "Passives are fine when the actor does not matter ('the server was restarted'). This rule is a prompt, "
        "not a verdict, so it is off by default and info-level when on."
    ),
)
def passive(doc: Document, opts: Mapping[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    for block in doc.prose_blocks:
        if block.kind == "heading":
            continue
        for m in PASSIVE.finditer(block.text):
            part = m.group("part").lower()
            if part in lexicon.ADJECTIVAL_PARTICIPLES:
                continue
            is_participle = part in lexicon.IRREGULAR_PARTICIPLES or (
                part.endswith("ed") and len(part) > 4 and not part.endswith("eed")
            )
            if not is_participle:
                continue
            start, end = block.start + m.start(), block.start + m.end()
            out.append(
                Finding(
                    "clarity/passive",
                    Severity.INFO,
                    f'"{doc.source[start:end]}": passive. Say who does it, if it matters.',
                    start,
                    end,
                )
            )
    return out


@rule(
    "clarity/long-sentence",
    "Long sentence",
    "A sentence over the word limit (35 by default).",
    Severity.INFO,
    options={"max-words": 35},
    examples=(
        Example(
            "The parser, which was rewritten last year to handle the new format that the vendor introduced without notice, now runs twice as fast as before, although memory use went up and the team that maintains it has grown from two people to five.",
            "The parser was rewritten last year for the vendor's new format. It now runs twice as fast, though memory use went up. The team maintaining it grew from two people to five.",
        ),
    ),
    why="Long sentences are not wrong, but past 35 words most readers lose the subject. Headings and bullets are exempt.",
)
def long_sentence(doc: Document, opts: Mapping[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    limit = int(opts.get("max-words", 35))
    for block in doc.blocks:
        if block.kind not in ("paragraph", "quote"):
            continue
        for s in doc.sentences(block):
            n = len(doc.words(s.start, s.end))
            if n > limit:
                out.append(
                    Finding(
                        "clarity/long-sentence",
                        Severity.INFO,
                        f"{n} words in one sentence (limit {limit}). Split it.",
                        s.start,
                        s.end,
                    )
                )
    return out


NOMINALISATION = re.compile(
    r"(?<![\w-])(?:the|a|an) (?P<noun>\w{5,}(?:tion|sion|ment|ance|ence|ation))\s+of(?![\w-])",
    re.IGNORECASE,
)
NOMINALISATION_SKIP = {
    "documentation",
    "information",
    "environment",
    "government",
    "department",
    "equipment",
    "experience",
}


@rule(
    "clarity/nominalisation",
    "Verb turned noun",
    "'The implementation of X' for 'implementing X', 'the creation of' for 'creating'.",
    Severity.INFO,
    examples=(Example("The implementation of caching led to the reduction of latency.", "Caching reduced latency."),),
    why="The verb is hiding inside the noun. Letting it out makes the sentence shorter and says who did what.",
)
def nominalisation(doc: Document, opts: Mapping[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    for block in doc.prose_blocks:
        if block.kind == "heading":
            continue
        for m in NOMINALISATION.finditer(block.text):
            if m.group("noun").lower() in NOMINALISATION_SKIP:
                continue
            start, end = block.start + m.start(), block.start + m.end()
            out.append(
                Finding(
                    "clarity/nominalisation",
                    Severity.INFO,
                    f'"{doc.source[start:end]}": a verb turned into a noun. Use the verb.',
                    start,
                    end,
                )
            )
    return out


DOUBLE_WORD = re.compile(r"(?<![\w-])(\w+)(\s+)\1(?![\w-])", re.IGNORECASE)
DOUBLE_WORD_OK = {"that", "had", "has", "have", "is", "do", "did", "was", "were", "very", "no", "bye", "so", "ha", "la"}


@rule(
    "clarity/double-word",
    "Doubled word",
    "'the the', 'is is': a word typed twice.",
    Severity.WARNING,
    fixable=True,
    examples=(Example("Run the the tests before you push.", "Run the tests before you push."),),
    why="A real typo that spell-checkers miss. Words that can legitimately double ('had had', 'that that') are skipped.",
)
def double_word(doc: Document, opts: Mapping[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    for block in doc.prose_blocks:
        for m in DOUBLE_WORD.finditer(block.text):
            word = m.group(1)
            if word.lower() in DOUBLE_WORD_OK or ("\n" in m.group(2) and block.kind == "item"):
                continue
            start, end = block.start + m.start(), block.start + m.end()
            out.append(
                Finding(
                    "clarity/double-word",
                    Severity.WARNING,
                    f'"{word}" is repeated.',
                    start,
                    end,
                    suggestion=f'Keep one "{word}"',
                    fix=Fix(block.start + m.start(2), end, ""),
                )
            )
    return out


@rule(
    "clarity/readability",
    "Hard to read",
    "A paragraph whose Flesch-Kincaid grade is above the limit (14 by default). Off by default.",
    Severity.INFO,
    enabled=False,
    options={"max-grade": 14, "min-words": 30},
    examples=(
        Example(
            "The utilisation of asynchronous invocation methodologies necessitates comprehensive reconsideration of exception-propagation semantics throughout heterogeneous distributed infrastructures, particularly regarding idempotency guarantees, compensating-transaction orchestration and the observability instrumentation that operational personnel require for diagnosing intermittent failures.",
            "Async calls change how errors travel, so the error handling needs a rethink. Retries must be safe to repeat, failed steps need an undo, and the on-call engineer needs enough logging to find a failure that only happens sometimes.",
        ),
    ),
    why=(
        "Reading-grade formulas count syllables and sentence length, so they punish long words even when they "
        "are the right words. Useful for marketing copy and support docs; noisy for technical reference. Off by default."
    ),
)
def readability(doc: Document, opts: Mapping[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    max_grade = float(opts.get("max-grade", 14))
    min_words = int(opts.get("min-words", 30))
    for block in doc.blocks:
        if block.kind not in ("paragraph", "quote"):
            continue
        sentences = doc.sentences(block)
        words = [doc.source[w.start : w.end] for w in doc.words(block.start, block.end)]
        if len(words) < min_words or not sentences:
            continue
        syllables = sum(count_syllables(w) for w in words)
        grade = 0.39 * len(words) / len(sentences) + 11.8 * syllables / len(words) - 15.59
        if grade > max_grade:
            out.append(
                Finding(
                    "clarity/readability",
                    Severity.INFO,
                    f"Reading grade {grade:.0f} (limit {max_grade:g}): long sentences and long words. Shorten both.",
                    block.start,
                    block.end,
                )
            )
    return out


VOWELS = re.compile(r"[aeiouy]+")


def count_syllables(word: str) -> int:
    w = word.lower().strip("'’-")
    if not w:
        return 0
    if len(w) <= 3:
        return 1
    if w.endswith("e") and not w.endswith(("le", "ee", "ye", "oe")):
        w = w[:-1]
    n = len(VOWELS.findall(w))
    return max(n, 1)
