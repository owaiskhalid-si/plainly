"""A Markdown-aware view of a text, with every offset still pointing at the original.

The trick is masking: `Document.masked` is the same length as `Document.source`, but code,
markup, URLs and comments are replaced by spaces. Rules run regexes over the masked text and
report offsets that are valid in the source, so every finding and every fix lands on the exact
characters the writer typed.
"""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass, field

Kind = str  # "heading" | "paragraph" | "item" | "quote" | "table"

FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
HEADING = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+|$)")
CLOSING_HASHES = re.compile(r"[ \t]+#+[ \t]*$")
SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
THEMATIC = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
LIST_ITEM = re.compile(r"^([ \t]*)([-*+]|\d{1,9}[.)])([ \t]+)(\[[ xX]\][ \t]+)?")
QUOTE = re.compile(r"^ {0,3}>[ \t]?")
LINK_DEF = re.compile(r"^ {0,3}\[[^\]]+\]:[ \t]*\S+")
HTML_BLOCK = re.compile(r"^ {0,3}</?[A-Za-z][^>]*>?")
TABLE_DELIM = re.compile(r"^[ \t]*\|?[ \t]*:?-{2,}:?[ \t]*(\|[ \t]*:?-{2,}:?[ \t]*)*\|?[ \t]*$")
DIRECTIVE = re.compile(r"<!--\s*plainly-(disable-next-line|disable-file|disable|enable)\b([^>]*?)-->")

# Inline markup, in the order it is removed.
INLINE_CODE = re.compile(r"(`+)(?!`)(.+?)(?<!`)\1(?!`)", re.DOTALL)
IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
LINK = re.compile(r"\[([^\]]*)\]\(([^)]*)\)")
REF_LINK = re.compile(r"\[([^\]]+)\]\[[^\]]*\]")
FOOTNOTE = re.compile(r"\[\^[^\]]+\]")
AUTOLINK = re.compile(r"<(?:https?://|mailto:)[^>]+>")
RAW_URL = re.compile(r"(?:https?://|www\.)[^\s<>()\"']+")
HTML_TAG = re.compile(r"</?[A-Za-z][^<>]*>")
EMPHASIS = re.compile(r"(?<!\w)[*_]{1,3}(?=\S)|(?<=\S)[*_]{1,3}(?!\w)|~~")
ESCAPE = re.compile(r"\\(?=[\\`*_{}\[\]()#+\-.!|>~])")

ABBREVIATIONS = {
    "e.g",
    "i.e",
    "etc",
    "vs",
    "cf",
    "mr",
    "mrs",
    "ms",
    "dr",
    "prof",
    "sr",
    "jr",
    "st",
    "no",
    "fig",
    "approx",
    "inc",
    "ltd",
    "co",
    "u.s",
    "u.k",
    "a.m",
    "p.m",
    "jan",
    "feb",
    "mar",
    "apr",
    "jun",
    "jul",
    "aug",
    "sep",
    "sept",
    "oct",
    "nov",
    "dec",
}
SENTENCE_END = re.compile(r"[.!?]+[\"'”’)\]]*(?=\s+|$)")
WORD = re.compile(r"[^\W_]+(?:['’\-][^\W_]+)*")


@dataclass(frozen=True)
class Span:
    start: int
    end: int


@dataclass
class Block:
    kind: Kind
    start: int
    end: int
    level: int = 0
    text: str = ""  # masked slice; set by the parser

    @property
    def span(self) -> Span:
        return Span(self.start, self.end)


@dataclass
class Disabled:
    start: int
    end: int
    rules: frozenset[str] | None  # None means every rule


@dataclass
class Document:
    source: str
    masked: str
    blocks: list[Block]
    disabled: list[Disabled] = field(default_factory=list)
    line_starts: list[int] = field(default_factory=list)

    # ----- positions ---------------------------------------------------------------------

    def position(self, offset: int) -> tuple[int, int]:
        """1-based (line, column) of an offset."""
        line = bisect_right(self.line_starts, offset) - 1
        return line + 1, offset - self.line_starts[line] + 1

    def line_text(self, line: int) -> str:
        start = self.line_starts[line - 1]
        end = self.line_starts[line] - 1 if line < len(self.line_starts) else len(self.source)
        return self.source[start:end].rstrip("\r")

    # ----- prose -------------------------------------------------------------------------

    @property
    def prose_blocks(self) -> list[Block]:
        return [b for b in self.blocks if b.kind != "table"]

    @property
    def word_count(self) -> int:
        return sum(len(WORD.findall(b.text)) for b in self.prose_blocks)

    def words(self, start: int, end: int) -> list[Span]:
        return [Span(start + m.start(), start + m.end()) for m in WORD.finditer(self.masked[start:end])]

    def sentences(self, block: Block) -> list[Span]:
        """Sentence spans inside a block, in source offsets, trimmed of whitespace."""
        text = block.text
        spans: list[Span] = []
        begin = 0
        for m in SENTENCE_END.finditer(text):
            if not _ends_sentence(text, m):
                continue
            spans.append(Span(block.start + begin, block.start + m.end()))
            begin = m.end()
        if text[begin:].strip():
            spans.append(Span(block.start + begin, block.start + len(text)))
        return [s for s in (self.trim(s) for s in spans) if s.end > s.start]

    def trim(self, span: Span) -> Span:
        start, end = span.start, span.end
        while start < end and self.masked[start].isspace():
            start += 1
        while end > start and self.masked[end - 1].isspace():
            end -= 1
        return Span(start, end)

    def text(self, span: Span) -> str:
        return self.source[span.start : span.end]

    def block_at(self, offset: int) -> Block | None:
        for block in self.blocks:
            if block.start <= offset < block.end:
                return block
        return None

    def is_sentence_start(self, offset: int) -> bool:
        """True when `offset` begins a sentence: block start, or after terminal punctuation."""
        block = self.block_at(offset)
        return block is not None and any(s.start == offset for s in self.sentences(block))

    # ----- directives ----------------------------------------------------------------------

    def is_disabled(self, rule: str, offset: int) -> bool:
        category = rule.split("/", 1)[0]
        for d in self.disabled:
            if d.start <= offset < d.end and (d.rules is None or rule in d.rules or category in d.rules):
                return True
        return False


def _ends_sentence(text: str, m: re.Match[str]) -> bool:
    """Decide whether a run of .!? really ends a sentence (not "e.g." or "J. Smith")."""
    end = m.end()
    if m.group() == ".":
        last = re.search(r"(\S+)$", text[: m.start()])
        if last:
            token = last.group(1).lower().lstrip("(\"'“‘")
            if token in ABBREVIATIONS or token.rstrip(".") in ABBREVIATIONS:
                return False
            if len(token) == 1 and token.isalpha():  # an initial
                return False
    nxt = text[end:].lstrip()
    return not nxt or not nxt[0].islower()


# ======================================================================================
# Parsing
# ======================================================================================


class _Masker:
    def __init__(self, source: str) -> None:
        self.chars = list(source)

    def mask(self, start: int, end: int) -> None:
        for i in range(start, end):
            if self.chars[i] != "\n":
                self.chars[i] = " "

    def text(self) -> str:
        return "".join(self.chars)


def _split_lines(source: str) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    pos = 0
    for raw in source.split("\n"):
        lines.append((pos, raw.rstrip("\r")))
        pos += len(raw) + 1
    return lines


def _rules_in(spec: str) -> frozenset[str] | None:
    names = [n for n in re.split(r"[,\s]+", spec.strip()) if n]
    return frozenset(names) if names else None


def parse(source: str) -> Document:
    masker = _Masker(source)
    lines = _split_lines(source)
    blocks: list[Block] = []
    disabled: list[Disabled] = []
    current: Block | None = None
    fence: tuple[str, int] | None = None  # fence character and length
    front_matter_end: int | None = None
    in_html = False
    in_comment = False
    list_content_indent: int | None = None
    disable_from: int | None = None
    disable_rules: frozenset[str] | None = None
    next_line: tuple[bool, frozenset[str] | None] = (False, None)

    def close() -> None:
        nonlocal current
        if current is not None:
            blocks.append(current)
            current = None

    for index, (start, line) in enumerate(lines):
        end = start + len(line)
        stripped = line.strip()

        # Front matter at the top of the file.
        if index == 0 and stripped in ("---", "+++"):
            closing = next((i for i, (_, t) in enumerate(lines[1:], 1) if t.strip() == stripped), None)
            if closing is not None:
                front_matter_end = closing
        if front_matter_end is not None and index <= front_matter_end:
            masker.mask(start, end)
            continue

        # Fenced code.
        if fence is not None:
            masker.mask(start, end)
            m = FENCE.match(line)
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= fence[1] and not stripped.strip("`~"):
                fence = None
            continue
        m = FENCE.match(line)
        if m:
            close()
            fence = (m.group(1)[0], len(m.group(1)))
            masker.mask(start, end)
            continue

        # HTML comments. Directives live in single-line comments.
        if in_comment:
            masker.mask(start, end)
            in_comment = "-->" not in line
            continue
        if stripped.startswith("<!--"):
            close()
            masker.mask(start, end)
            if "-->" not in line:
                in_comment = True
                continue
            for d in DIRECTIVE.finditer(line):
                kind_, spec = d.group(1), d.group(2)
                if kind_ == "disable-file":
                    disabled.append(Disabled(0, len(source), None))
                elif kind_ == "disable":
                    disable_from, disable_rules = end, _rules_in(spec)
                elif kind_ == "enable" and disable_from is not None:
                    disabled.append(Disabled(disable_from, start, disable_rules))
                    disable_from = None
                elif kind_ == "disable-next-line":
                    next_line = (True, _rules_in(spec))
            continue

        # Blank line ends the block.
        if not stripped:
            close()
            in_html = False
            continue

        if in_html:
            masker.mask(start, end)
            continue

        if next_line[0]:
            disabled.append(Disabled(start, end + 1, next_line[1]))
            next_line = (False, None)

        if HTML_BLOCK.match(line) and not stripped.startswith("<!"):
            close()
            in_html = True
            masker.mask(start, end)
            continue
        if LINK_DEF.match(line):
            close()
            masker.mask(start, end)
            continue
        if "|" in line and TABLE_DELIM.match(line):
            if current is not None:
                current.kind = "table"
            masker.mask(start, end)
            continue
        if SETEXT.match(line):
            if current is not None and current.kind == "paragraph":
                current.kind = "heading"
                current.level = 1 if stripped[0] == "=" else 2
                close()
            masker.mask(start, end)
            continue
        if THEMATIC.match(line):
            close()
            masker.mask(start, end)
            continue

        content_start = start
        kind: Kind = "paragraph"

        q = QUOTE.match(line)
        if q:
            if current is not None and current.kind != "quote":
                close()
            masker.mask(start, start + q.end())
            kind = "quote"
            content_start = start + q.end()
            line = line[q.end() :]
            if not line.strip():
                close()
                continue

        h = HEADING.match(line)
        if h and kind == "paragraph":
            close()
            masker.mask(content_start, content_start + h.end())
            text_end = end
            c = CLOSING_HASHES.search(line)
            if c:
                masker.mask(content_start + c.start(), end)
                text_end = content_start + c.start()
            blocks.append(Block("heading", content_start + h.end(), text_end, len(h.group(1))))
            _mask_inline(masker, source, content_start + h.end(), text_end)
            list_content_indent = None
            continue

        li = LIST_ITEM.match(line)
        if li and kind == "paragraph":
            close()
            masker.mask(content_start, content_start + li.end())
            level = len(li.group(1).expandtabs(4))
            list_content_indent = level + len(li.group(2)) + len(li.group(3))
            current = Block("item", content_start + li.end(), end, level)
            _mask_inline(masker, source, current.start, end)
            continue

        indent = len(line[: len(line) - len(line.lstrip(" \t"))].expandtabs(4))
        if list_content_indent is not None and indent < list_content_indent and current is None:
            list_content_indent = None
        if indent >= 4 and list_content_indent is None and current is None:
            masker.mask(start, end)  # indented code
            continue

        if current is None:
            current = Block(kind, content_start, end)
        else:
            current.end = end
        _mask_inline(masker, source, content_start, end)
        if (stripped.startswith("|") or stripped.endswith("|")) and stripped.count("|") >= 2:
            current.kind = "table"
            for i in range(content_start, end):
                if source[i] == "|":
                    masker.mask(i, i + 1)

    close()
    if disable_from is not None:
        disabled.append(Disabled(disable_from, len(source), disable_rules))

    masked = masker.text()
    for block in blocks:
        block.text = masked[block.start : block.end]
    return Document(source=source, masked=masked, blocks=blocks, disabled=disabled, line_starts=[s for s, _ in lines])


def _mask_inline(masker: _Masker, source: str, start: int, end: int) -> None:
    text = source[start:end]
    for m in INLINE_CODE.finditer(text):
        masker.mask(start + m.start(), start + m.end())
    once = "".join(masker.chars[start:end])
    for m in IMAGE.finditer(once):
        masker.mask(start + m.start(), start + m.end())
    for pattern in (LINK, REF_LINK):
        for m in pattern.finditer(once):
            masker.mask(start + m.start(), start + m.start(1))
            masker.mask(start + m.end(1), start + m.end())
    for pattern in (FOOTNOTE, AUTOLINK, RAW_URL, HTML_TAG, EMPHASIS, ESCAPE):
        for m in pattern.finditer(once):
            masker.mask(start + m.start(), start + m.end())
