"""Patterns that mark text as generated: the vocabulary, the openers, the set-ups, the closers."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from plainly import lexicon
from plainly.document import Document
from plainly.findings import Finding, Severity
from plainly.rules.base import Example, is_mention, match_terms, rule


@rule(
    "tells/vocabulary",
    "Model vocabulary",
    "Words and phrases language models use far more than people do: delve, tapestry, testament, realm, seamless, robust, crucial, embark, leverage.",
    Severity.WARNING,
    fixable=True,
    options={"allow": []},
    examples=(
        Example("Let's delve into the robust, seamless architecture.", "Here is how the architecture handles failure."),
        Example("This tool is a testament to the power of automation.", "This tool saves the team two hours a week."),
    ),
    why=(
        "One of these words in a long piece is nothing. A handful per page is the single most "
        "reliable sign that nobody chose the words. The score tracks the density; each hit shows a plainer choice."
    ),
)
def vocabulary(doc: Document, opts: Mapping[str, Any]) -> list[Finding]:
    return match_terms(
        doc,
        "tells/vocabulary",
        lexicon.AI_TELLS,
        opts,
        Severity.WARNING,
        lambda text, term: f'"{text}": {term.note}.',
    )


@rule(
    "tells/opener-cliche",
    "Clichéd opener",
    "A paragraph that starts the way generated articles start: 'In today's fast-paced world', 'Have you ever wondered', 'In this article, we will'.",
    Severity.WARNING,
    examples=(
        Example(
            "In today's fast-paced digital landscape, caching matters more than ever.",
            "Caching cut our p95 latency from 900 ms to 120 ms.",
        ),
        Example(
            "In this article, we will explore how to set up a reverse proxy.",
            "A reverse proxy in front of the app does three jobs.",
        ),
    ),
    why="The first sentence is the one readers use to decide whether to keep going. These openers tell them nothing.",
)
def opener_cliche(doc: Document, opts: Mapping[str, Any]) -> list[Finding]:
    return match_terms(
        doc,
        "tells/opener-cliche",
        lexicon.OPENERS,
        opts,
        Severity.WARNING,
        lambda text, term: f'Opens with "{text}": {term.note}.',
        kinds=("paragraph", "quote"),
        only_sentence_start=True,
    )


@rule(
    "tells/summary-closer",
    "Summary closer",
    "'In conclusion', 'Overall', 'Ultimately', 'At the end of the day': announcing the end instead of ending.",
    Severity.WARNING,
    fixable=True,
    examples=(
        Example(
            "In conclusion, caching is a powerful tool that every team should consider.",
            "Cache the catalogue, not the cart.",
        ),
        Example("Ultimately, the choice depends on your needs.", "Pick Postgres unless you need the document model."),
    ),
    why="Readers can see the last paragraph. If it is a summary, it is a summary without the label; if it is not, the label is false.",
)
def summary_closer(doc: Document, opts: Mapping[str, Any]) -> list[Finding]:
    return match_terms(
        doc,
        "tells/summary-closer",
        lexicon.CLOSERS,
        opts,
        Severity.WARNING,
        lambda text, term: f'"{text}": {term.note}.',
        kinds=("paragraph", "item", "quote"),
        only_sentence_start=True,
    )


@rule(
    "tells/setup-fragment",
    "Set-up fragment",
    "A drumroll before the point: 'Here's the thing.', 'The best part?', 'Spoiler:', 'Let that sink in.'",
    Severity.WARNING,
    examples=(
        Example("The best part? It runs offline.", "It runs offline."),
        Example("Here's the thing: nobody reads the changelog.", "Nobody reads the changelog."),
    ),
    why="A one-beat fragment that promises a reveal is a social-media habit models copied. The point is stronger without the pause.",
)
def setup_fragment(doc: Document, opts: Mapping[str, Any]) -> list[Finding]:
    return match_terms(
        doc,
        "tells/setup-fragment",
        lexicon.SETUP_FRAGMENTS,
        opts,
        Severity.WARNING,
        lambda text, term: f'"{text}": {term.note}.',
        kinds=("paragraph", "item", "quote", "heading"),
    )


@rule(
    "tells/not-just-but",
    "'Not just X, but Y'",
    "The contrast frame models lean on: 'not just a tool, but a partner', 'it's not about speed; it's about trust', 'more than just'.",
    Severity.WARNING,
    examples=(
        Example(
            "This isn't just a linter; it's a writing partner.", "This linter marks the sentences a reader would skip."
        ),
        Example(
            "Testing is not only about catching bugs, but also about confidence.",
            "Tests catch bugs and let you refactor without fear.",
        ),
    ),
    why="The frame sets up a straw man (X) to knock down. Say Y.",
)
def not_just_but(doc: Document, opts: Mapping[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    for block in doc.prose_blocks:
        for m in lexicon.NOT_JUST_BUT.finditer(block.text):
            start, end = block.start + m.start(), block.start + m.end()
            if is_mention(doc, start, end + 2) or is_mention(doc, start, end):
                continue
            out.append(
                Finding(
                    "tells/not-just-but",
                    Severity.WARNING,
                    f'"{_short(doc.source[start:end])}": the "not just X, but Y" frame. Say Y.',
                    start,
                    end,
                    weight=3,
                )
            )
    return out


@rule(
    "tells/rhetorical-question",
    "Rhetorical question and answer",
    "A question the writer answers in the next breath: 'Why? Because...', 'The answer is simple.', 'So what does this mean?'",
    Severity.WARNING,
    examples=(
        Example(
            "Why does this matter? Because downtime costs money.",
            "Downtime costs money: about $400 a minute for this shop.",
        ),
        Example("So what is the catch? The answer is simple: memory.", "The catch is memory."),
    ),
    why="A question nobody asked, answered by the person who asked it, is a stall. State the answer.",
)
def rhetorical_question(doc: Document, opts: Mapping[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    for block in doc.prose_blocks:
        if block.kind == "heading":
            continue
        for m in lexicon.RHETORICAL.finditer(block.text):
            start, end = block.start + m.start(), block.start + m.end()
            out.append(
                Finding(
                    "tells/rhetorical-question",
                    Severity.WARNING,
                    f'"{_short(doc.source[start:end])}": a question asked only to be answered. State the answer.',
                    start,
                    end,
                    weight=2,
                )
            )
    return out


EM_DASH = re.compile(r"—|(?<=\w)\s*–\s*(?=\w)|(?<=\s)--(?=\s)|(?<=\w)--(?=\w)")


@rule(
    "tells/em-dash",
    "Em-dash habit",
    "Too many em dashes for the length of the text. People use them; models use them in every paragraph.",
    Severity.WARNING,
    options={"per-thousand": 4, "min": 3},
    examples=(
        Example(
            "Caching helps — a lot — but only when the data is stable — which it rarely is.",
            "Caching helps, but only when the data is stable, and it rarely is.",
        ),
    ),
    why=(
        "An em dash is fine. Four per thousand words is a habit, and the habit is one of the easiest "
        "tells to spot. Commas, full stops and parentheses do the same jobs."
    ),
)
def em_dash(doc: Document, opts: Mapping[str, Any]) -> list[Finding]:
    hits = [block.start + m.start() for block in doc.prose_blocks for m in EM_DASH.finditer(block.text)]
    words = max(doc.word_count, 1)
    rate = len(hits) / words * 1000
    minimum = int(opts.get("min", 3))
    limit = float(opts.get("per-thousand", 4))
    if len(hits) < minimum or rate <= limit:
        return []
    hits.sort()
    at = hits[minimum - 1]
    return [
        Finding(
            "tells/em-dash",
            Severity.WARNING,
            f"{len(hits)} em dashes in {words} words ({rate:.0f} per 1,000; the limit is {limit:g}). "
            "Use commas, full stops or parentheses for most of them.",
            at,
            at + 1,
            weight=2,
        )
    ]


TRIAD = re.compile(r"(?<![\w-])([A-Za-z][a-z]{2,}), ([a-z]{3,}),? (?:and|or) ([a-z]{3,})(?![\w-])")


@rule(
    "tells/triad",
    "Triad habit",
    "Three-item lists of single words ('fast, reliable, and scalable') showing up again and again.",
    Severity.INFO,
    options={"per-thousand": 6, "min": 3},
    examples=(
        Example(
            "The API is fast, simple, and secure. Setup is quick, painless, and free. The docs are short, clear, and kind.",
            "The API answers in under 50 ms. Setup takes one command. The docs fit on one page.",
        ),
    ),
    why="The rule of three is a real rhetorical device. Used in every other sentence it becomes a drumbeat, and each item in the triad is usually an adjective that could have been a fact.",
)
def triad(doc: Document, opts: Mapping[str, Any]) -> list[Finding]:
    hits = [
        (block.start + m.start(), block.start + m.end())
        for block in doc.prose_blocks
        if block.kind != "heading"
        for m in TRIAD.finditer(block.text)
    ]
    words = max(doc.word_count, 1)
    rate = len(hits) / words * 1000
    minimum = int(opts.get("min", 3))
    if len(hits) < minimum or rate <= float(opts.get("per-thousand", 6)):
        return []
    hits.sort()
    start, end = hits[minimum - 1]
    return [
        Finding(
            "tells/triad",
            Severity.INFO,
            f'"{doc.source[start:end]}" is three-item list number {minimum} of {len(hits)} in {words} words. '
            "Vary the rhythm, or swap an adjective for a fact.",
            start,
            end,
        )
    ]


def _short(text: str, limit: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"
