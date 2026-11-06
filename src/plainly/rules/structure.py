"""Shape-of-the-text rules: the bullet style, the rhythm, the headings, the sign-off."""

from __future__ import annotations

import re
import statistics
from collections.abc import Mapping
from typing import Any

from plainly import lexicon
from plainly.document import WORD, Document
from plainly.findings import Finding, Severity
from plainly.rules.base import Example, match_terms, rule

BOLD_LEAD = re.compile(r"^\s*(?:\*\*|__)[^*_\n]{1,60}?(?::\s*(?:\*\*|__)|(?:\*\*|__)\s*[:：–—-])")
TRAILING_PUNCT = re.compile(r"[.!?:;,]+$")


@rule(
    "structure/bold-lead-bullets",
    "Bold-label bullets",
    "A run of bullets that each start with a bold label and a colon: '**Speed:** it is fast.'",
    Severity.WARNING,
    options={"min": 3},
    examples=(
        Example(
            "- **Speed:** responses in under 50 ms\n- **Cost:** free for 10k requests\n- **Support:** email only",
            "Responses come back in under 50 ms. The first 10k requests are free. Support is by email.",
        ),
    ),
    why=(
        "This is the default shape of a generated answer: a list where each item is a heading in disguise. "
        "Three or more in a row almost always read better as sentences, or as a table if the labels are real columns."
    ),
)
def bold_lead_bullets(doc: Document, opts: Mapping[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    minimum = int(opts.get("min", 3))
    run: list[int] = []
    previous_end = -1

    def flush() -> None:
        if len(run) >= minimum:
            first = run[0]
            block = doc.block_at(first)
            assert block is not None
            out.append(
                Finding(
                    "structure/bold-lead-bullets",
                    Severity.WARNING,
                    f"{len(run)} bullets in a row open with a bold label and a colon. "
                    "Write them as sentences, or as a table if the labels are columns.",
                    block.start,
                    block.end,
                    weight=2,
                )
            )
        run.clear()

    for block in doc.blocks:
        if block.kind == "item":
            raw = doc.source[block.start : block.end]
            # Items must be consecutive: nothing but whitespace between them.
            if previous_end >= 0 and doc.source[previous_end : block.start].strip(" \t\n\r-*+0123456789.)[]x"):
                flush()
            if BOLD_LEAD.match(raw):
                run.append(block.start)
            else:
                flush()
            previous_end = block.end
        else:
            flush()
            previous_end = -1
    flush()
    return out


@rule(
    "structure/same-opener",
    "Same opener",
    "Three or more sentences in a row (or paragraphs, or bullets) that start with the same word.",
    Severity.INFO,
    options={"min": 3, "ignore": ["i", "the", "a", "an", "if", "when", "you", "we", "it", "this"]},
    examples=(
        Example(
            "Caching reduces load. Caching also hides latency. Caching can serve stale data.",
            "Caching reduces load and hides latency, at the price of serving stale data.",
        ),
    ),
    why="Anaphora is a device; by accident it is a drone. Common function words are ignored.",
)
def same_opener(doc: Document, opts: Mapping[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    minimum = int(opts.get("min", 3))
    ignore = {w.lower() for w in opts.get("ignore", ())}

    def scan(units: list[tuple[int, int]], what: str) -> None:
        run_word = ""
        run: list[tuple[int, int]] = []
        for start, end in units:
            m = WORD.search(doc.masked, start, end)
            word = m.group().lower() if m else ""
            if word and word == run_word:
                run.append((start, end))
            else:
                if len(run) >= minimum and run_word not in ignore:
                    out.append(_opener_finding(doc, run, run_word, what))
                run_word, run = word, [(start, end)]
        if len(run) >= minimum and run_word not in ignore:
            out.append(_opener_finding(doc, run, run_word, what))

    for block in doc.prose_blocks:
        if block.kind in ("paragraph", "quote"):
            scan([(s.start, s.end) for s in doc.sentences(block)], "sentences")
    scan([(b.start, b.end) for b in doc.blocks if b.kind == "paragraph"], "paragraphs")
    scan([(b.start, b.end) for b in doc.blocks if b.kind == "item"], "bullets")
    return out


def _opener_finding(doc: Document, run: list[tuple[int, int]], word: str, what: str) -> Finding:
    first = run[0]
    m = WORD.search(doc.masked, first[0], first[1])
    assert m is not None
    return Finding(
        "structure/same-opener",
        Severity.INFO,
        f'{len(run)} {what} in a row start with "{doc.source[m.start() : m.end()]}". Vary the openings.',
        m.start(),
        m.end(),
    )


@rule(
    "structure/sentence-rhythm",
    "Flat rhythm",
    "A paragraph whose sentences are all about the same length.",
    Severity.INFO,
    options={"min-sentences": 5, "max-variation": 0.22},
    examples=(
        Example(
            "The cache stores recent pages. The cache expires them hourly. The cache ignores logged-in users. The cache lives in Redis. The cache is optional.",
            "The cache stores recent pages and expires them hourly. Logged-in users bypass it. It lives in Redis, and it is optional.",
        ),
    ),
    why=(
        "People write long sentences and then short ones. Generated prose tends to settle on one length. "
        "This rule measures the spread of sentence lengths in a paragraph and flags the flat ones."
    ),
)
def sentence_rhythm(doc: Document, opts: Mapping[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    min_sentences = int(opts.get("min-sentences", 5))
    limit = float(opts.get("max-variation", 0.22))
    for block in doc.blocks:
        if block.kind not in ("paragraph", "quote"):
            continue
        lengths = [len(doc.words(s.start, s.end)) for s in doc.sentences(block)]
        lengths = [n for n in lengths if n > 0]
        if len(lengths) < min_sentences:
            continue
        mean = statistics.fmean(lengths)
        if mean == 0:
            continue
        variation = statistics.pstdev(lengths) / mean
        if variation < limit:
            out.append(
                Finding(
                    "structure/sentence-rhythm",
                    Severity.INFO,
                    f"{len(lengths)} sentences of {min(lengths)}–{max(lengths)} words, all near {mean:.0f}. "
                    "Vary the length: join two, cut one short.",
                    block.start,
                    block.end,
                )
            )
    return out


@rule(
    "structure/emoji-heading",
    "Emoji in heading",
    "A heading with an emoji in it: '🚀 Getting started'.",
    Severity.INFO,
    examples=(Example("## 🚀 Getting started", "## Getting started"),),
    why="Emoji headings are a README fashion that generated READMEs copy wholesale. They also break anchors and screen readers.",
)
def emoji_heading(doc: Document, opts: Mapping[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    for block in doc.blocks:
        if block.kind != "heading":
            continue
        m = lexicon.EMOJI.search(block.text)
        if m:
            out.append(
                Finding(
                    "structure/emoji-heading",
                    Severity.INFO,
                    "Emoji in a heading. Headings are navigation; keep them plain.",
                    block.start + m.start(),
                    block.start + m.end(),
                )
            )
    return out


@rule(
    "structure/sign-off",
    "Sign-off",
    "'Happy coding!', 'Stay tuned', 'I hope this helps', 'Feel free to reach out': a wave at the door.",
    Severity.WARNING,
    examples=(
        Example(
            "That's it! Happy coding, and feel free to reach out with questions.", "(end on the last useful sentence)"
        ),
    ),
    why="A piece ends when the information ends. Generated text adds a goodbye.",
)
def sign_off(doc: Document, opts: Mapping[str, Any]) -> list[Finding]:
    return match_terms(
        doc,
        "structure/sign-off",
        lexicon.SIGN_OFFS,
        opts,
        Severity.WARNING,
        lambda text, term: f'"{text}": {term.note}.',
        kinds=("paragraph", "item", "quote", "heading"),
    )


@rule(
    "structure/question-heading",
    "Question heading",
    "A heading phrased as a question: 'What is a reverse proxy?', 'Why does this matter?'",
    Severity.INFO,
    enabled=False,
    examples=(Example("## What is a reverse proxy?", "## Reverse proxies"),),
    why="Search-engine articles ask the question in the heading so the engine matches it. Readers prefer the answer. Off by default; FAQ pages are a fair use.",
)
def question_heading(doc: Document, opts: Mapping[str, Any]) -> list[Finding]:
    out: list[Finding] = []
    for block in doc.blocks:
        if block.kind == "heading" and block.text.rstrip().endswith("?"):
            out.append(
                Finding(
                    "structure/question-heading",
                    Severity.INFO,
                    "Heading is a question. Name the thing the section is about instead.",
                    block.start,
                    block.end,
                )
            )
    return out
