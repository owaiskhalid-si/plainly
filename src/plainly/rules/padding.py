"""Words that take up room without adding anything. Most of these fixes are safe to apply."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from plainly import lexicon
from plainly.document import Document
from plainly.findings import Finding, Severity
from plainly.rules.base import Example, deletion_fix, match_terms, rule


@rule(
    "padding/throat-clearing",
    "Throat-clearing",
    "'It is important to note that', 'Needless to say', 'Basically,': a run-up before the sentence starts.",
    Severity.WARNING,
    fixable=True,
    examples=(
        Example("It is important to note that the cache expires after an hour.", "The cache expires after an hour."),
        Example("Needless to say, backups matter.", "Backups matter."),
    ),
    why="The sentence after the phrase is the sentence. Deleting the run-up never changes the meaning, which is why the fix is automatic.",
)
def throat_clearing(doc: Document, opts: Mapping[str, Any]) -> list[Finding]:
    return match_terms(
        doc,
        "padding/throat-clearing",
        lexicon.THROAT_CLEARING,
        opts,
        Severity.WARNING,
        lambda text, term: f'"{text}": {term.note}.',
        kinds=("paragraph", "item", "quote"),
    )


@rule(
    "padding/wordy",
    "Wordy phrase",
    "A long way of saying a short thing: 'in order to', 'utilize', 'prior to', 'due to the fact that'.",
    Severity.INFO,
    fixable=True,
    examples=(
        Example(
            "In order to utilize the API prior to launch, contact support.",
            "To use the API before launch, contact support.",
        ),
    ),
    why="Each of these has a one-word equivalent that every reader knows. The fix swaps it in.",
)
def wordy(doc: Document, opts: Mapping[str, Any]) -> list[Finding]:
    return match_terms(
        doc,
        "padding/wordy",
        lexicon.WORDY,
        opts,
        Severity.INFO,
        lambda text, term: f'"{text}": {term.note}.',
    )


@rule(
    "padding/vague-quantity",
    "Vague quantity",
    "'Numerous', 'a myriad of', 'a variety of', 'various': a quantity that avoids saying how many.",
    Severity.INFO,
    fixable=True,
    examples=(
        Example(
            "We fixed numerous bugs across a variety of modules.", "We fixed 14 bugs in the auth and billing modules."
        ),
    ),
    why="A number is more useful than 'numerous'. When you do not have the number, 'many' or 'several' is at least honest about it.",
)
def vague_quantity(doc: Document, opts: Mapping[str, Any]) -> list[Finding]:
    return match_terms(
        doc,
        "padding/vague-quantity",
        lexicon.VAGUE_QUANTITY,
        opts,
        Severity.INFO,
        lambda text, term: f'"{text}": {term.note}.',
    )


@rule(
    "padding/intensifier",
    "Empty intensifier",
    "'Very', 'really', 'truly', 'incredibly', 'extremely': words that make the next word weaker.",
    Severity.INFO,
    fixable=True,
    examples=(Example("The migration was very slow and really painful.", "The migration took nine hours."),),
    why="'Very fast' is slower than 'fast'. If the word needs propping up, pick a better word or give the measurement.",
)
def intensifier(doc: Document, opts: Mapping[str, Any]) -> list[Finding]:
    return match_terms(
        doc,
        "padding/intensifier",
        lexicon.INTENSIFIERS,
        opts,
        Severity.INFO,
        lambda text, term: f'"{text}": {term.note}.',
        kinds=("paragraph", "item", "quote"),
    )


@rule(
    "padding/double-hedge",
    "Double hedge",
    "Two hedges in a row: 'may potentially', 'could possibly', 'seems to perhaps'.",
    Severity.INFO,
    fixable=True,
    examples=(Example("This change may potentially affect older clients.", "This change may affect older clients."),),
    why="One hedge is a judgement. Two is a writer who has not decided.",
)
def double_hedge(doc: Document, opts: Mapping[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    for block in doc.prose_blocks:
        for m in lexicon.DOUBLE_HEDGE.finditer(block.text):
            start, end = block.start + m.start(), block.start + m.end()
            words = doc.source[start:end].split()
            # Keep the first word (the modal), drop the second (the adverb).
            second_start = start + len(words[0])
            while doc.source[second_start] in " \t":
                second_start += 1
            f = Finding(
                "padding/double-hedge",
                Severity.INFO,
                f'"{doc.source[start:end]}": two hedges in a row. One is enough.',
                start,
                end,
                suggestion=f'Say "{words[0]}"',
            )
            f.fix = deletion_fix(doc, second_start, end)
            out.append(f)
    return out
