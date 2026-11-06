"""The Markdown view: what gets masked, and that offsets always point at the source."""

from plainly.document import parse


def kinds(text: str) -> list[tuple[str, str]]:
    doc = parse(text)
    return [(b.kind, b.text.strip()) for b in doc.blocks]


def test_masked_is_same_length_and_only_masks() -> None:
    src = "# Title\n\nSome `code` and [a link](http://x.y) here.\n\n```py\ndelve()\n```\n"
    doc = parse(src)
    assert len(doc.masked) == len(src)
    for a, b in zip(src, doc.masked, strict=True):
        assert b == a or b == " "


def test_fenced_code_is_not_prose() -> None:
    doc = parse("Before.\n\n```\nWe delve into robust code.\n```\n\nAfter.\n")
    assert "delve" not in doc.masked
    assert kinds(doc.source) == [("paragraph", "Before."), ("paragraph", "After.")]


def test_tilde_fence_and_indented_code() -> None:
    doc = parse("Para.\n\n~~~\ndelve\n~~~\n\n    delve indented\n\nEnd.\n")
    assert "delve" not in doc.masked


def test_inline_code_links_and_urls_are_masked_but_link_text_kept() -> None:
    src = "Use `delve` or [a seamless link](https://delve.example/robust) at https://x.y/delve now."
    doc = parse(src)
    assert "seamless" in doc.masked
    assert "delve" not in doc.masked
    assert "https" not in doc.masked
    block = doc.blocks[0]
    assert doc.source[block.start : block.end] == src


def test_front_matter_and_html_comment_are_masked() -> None:
    src = "---\ntitle: delve\n---\n\n<!-- robust comment -->\nReal text.\n"
    doc = parse(src)
    assert "delve" not in doc.masked
    assert "robust" not in doc.masked
    assert kinds(src) == [("paragraph", "Real text.")]


def test_headings_items_quotes_and_tables() -> None:
    src = "# Head\n\n- one\n- two\n\n> quoted\n\n| a | b |\n|---|---|\n| c | d |\n\nSetext\n======\n"
    got = kinds(src)
    assert [k for k, _ in got] == ["heading", "item", "item", "quote", "table", "heading"]
    assert [t for k, t in got if k != "table"] == ["Head", "one", "two", "quoted", "Setext"]
    assert "|" not in got[4][1] and "---" not in got[4][1]
    doc = parse(src)
    assert doc.prose_blocks[-1].kind == "heading"
    assert all(b.kind != "table" for b in doc.prose_blocks)


def test_emphasis_markers_masked_but_snake_case_kept() -> None:
    doc = parse("This is **bold** and _it_ and a snake_case_name and __init__.")
    assert "snake_case_name" in doc.masked
    assert "**" not in doc.masked
    assert "bold" in doc.masked


def test_positions_are_one_based() -> None:
    doc = parse("ab\ncd\n")
    assert doc.position(0) == (1, 1)
    assert doc.position(3) == (2, 1)
    assert doc.position(4) == (2, 2)


def test_sentences_handle_abbreviations_and_initials() -> None:
    doc = parse("We met Dr. Smith, e.g. at 3 p.m. in the lab. Then J. Doe left. Done!")
    sents = [doc.text(s) for s in doc.sentences(doc.blocks[0])]
    assert sents == ["We met Dr. Smith, e.g. at 3 p.m. in the lab.", "Then J. Doe left.", "Done!"]


def test_word_count_ignores_code_and_markup() -> None:
    doc = parse("One two `three` [four](http://x) **five**\n\n```\nsix seven\n```\n")
    assert doc.word_count == 4


def test_directives() -> None:
    src = (
        "delve one\n\n<!-- plainly-disable -->\ndelve two\n<!-- plainly-enable -->\n\n"
        "<!-- plainly-disable-next-line tells/vocabulary -->\ndelve three\n\ndelve four\n"
    )
    doc = parse(src)
    offsets = [m for m in range(len(src)) if src.startswith("delve", m)]
    assert not doc.is_disabled("tells/vocabulary", offsets[0])
    assert doc.is_disabled("tells/vocabulary", offsets[1])
    assert doc.is_disabled("tells/vocabulary", offsets[2])
    assert not doc.is_disabled("padding/wordy", offsets[2])
    assert not doc.is_disabled("tells/vocabulary", offsets[3])


def test_disable_file_and_category_names() -> None:
    doc = parse("<!-- plainly-disable tells -->\ndelve\n")
    at = doc.source.index("delve")
    assert doc.is_disabled("tells/vocabulary", at)
    assert not doc.is_disabled("padding/wordy", at)
    doc2 = parse("<!-- plainly-disable-file -->\ndelve\n")
    assert doc2.is_disabled("anything/at-all", doc2.source.index("delve"))


def test_crlf_sources_keep_offsets() -> None:
    src = "# T\r\n\r\nWe delve here.\r\n"
    doc = parse(src)
    at = src.index("delve")
    assert doc.masked[at : at + 5] == "delve"
    assert doc.position(at) == (3, 4)
