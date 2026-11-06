"""One or two cases per rule: it fires on the pattern and stays quiet on plain text."""

from __future__ import annotations

import pytest

from plainly.engine import lint_text
from plainly.rules import REGISTRY


def rules_hit(text: str, select: list[str] | None = None) -> list[str]:
    return [f.rule for f in lint_text(text, select=select).findings]


def texts(text: str, rule: str) -> list[str]:
    return [f.text for f in lint_text(text, select=[rule]).findings]


# ----- tells -------------------------------------------------------------------------------


def test_vocabulary_hits_and_suggests() -> None:
    report = lint_text("Let's delve into the robust architecture.")
    hits = {f.text: f for f in report.findings if f.rule == "tells/vocabulary"}
    assert set(hits) == {"delve", "robust"}
    assert hits["delve"].suggestion == 'Replace with "look"'
    assert hits["robust"].fix is None


def test_vocabulary_is_case_insensitive_and_word_bounded() -> None:
    assert texts("Delve. Delved. Delving. Shelve. Delves.", "tells/vocabulary") == [
        "Delve",
        "Delved",
        "Delving",
        "Delves",
    ]


def test_opener_cliche_only_at_sentence_start() -> None:
    assert texts("In today's market, prices rose.", "tells/opener-cliche") == ["In today's"]
    assert texts("Prices rose in today's market.", "tells/opener-cliche") == []
    assert texts("- In today's market", "tells/opener-cliche") == []  # bullets are exempt


def test_summary_closer_fix_recapitalises() -> None:
    report = lint_text("In conclusion, caching helps.", select=["tells/summary-closer"], fix=True)
    assert report.fixed_text == "Caching helps."


def test_setup_fragment() -> None:
    assert texts("The best part? It runs offline. Here's the thing: it works.", "tells/setup-fragment") == [
        "The best part?",
        "Here's the thing:",
    ]


def test_not_just_but_variants() -> None:
    for s in (
        "This isn't just a linter; it's a partner.",
        "Testing is not only about bugs, but also about confidence.",
        "It's not about speed — it's about trust.",
        "It is more than just a tool.",
    ):
        assert rules_hit(s, ["tells/not-just-but"]) == ["tells/not-just-but"], s
    assert rules_hit("It is not just. But it is fair.", ["tells/not-just-but"]) == []


def test_rhetorical_question() -> None:
    assert rules_hit("Why does this matter? Because downtime costs money.", ["tells/rhetorical-question"])
    assert rules_hit("The answer is simple.", ["tells/rhetorical-question"])
    assert not rules_hit("Why did the build fail? The log says the disk was full.", ["tells/rhetorical-question"])


def test_em_dash_density() -> None:
    body = "word " * 100
    three = body + "a — b — c — d."
    assert rules_hit(three, ["tells/em-dash"]) == ["tells/em-dash"]
    two = body + "a — b — c."
    assert rules_hit(two, ["tells/em-dash"]) == []
    long_text = ("word " * 1000) + "a — b — c — d."
    assert rules_hit(long_text, ["tells/em-dash"]) == []


def test_triad_density() -> None:
    text = "It is fast, simple, and secure. Setup is quick, painless, and free. Docs are short, clear, and kind."
    report = lint_text(text, select=["tells/triad"])
    assert [f.rule for f in report.findings] == ["tells/triad"]
    assert "number 3 of 3" in report.findings[0].message


# ----- padding ------------------------------------------------------------------------------


def test_throat_clearing_fix_deletes_and_capitalises() -> None:
    report = lint_text("It is important to note that the cache expires.", fix=True)
    assert report.fixed_text == "The cache expires."
    report = lint_text("Caching helps. Needless to say, backups matter.", fix=True)
    assert report.fixed_text == "Caching helps. Backups matter."


def test_replacements_keep_verb_endings_and_articles() -> None:
    report = lint_text("It empowers teams. She leveraged it. We are leveraging it. A pivotal tool.", fix=True)
    assert report.fixed_text == "It helps teams. She used it. We are using it. An important tool."


def test_wordy_replacements_keep_case() -> None:
    report = lint_text("In order to utilize it, call support prior to launch.", select=["padding/wordy"], fix=True)
    assert report.fixed_text == "To use it, call support before launch."


def test_intensifier_fix_handles_end_of_sentence() -> None:
    report = lint_text("The test was very slow. It was slow very.", select=["padding/intensifier"], fix=True)
    assert report.fixed_text == "The test was slow. It was slow."


def test_vague_quantity() -> None:
    assert texts("We fixed numerous bugs in various modules.", "padding/vague-quantity") == ["numerous", "various"]


def test_double_hedge_keeps_the_modal() -> None:
    report = lint_text("This may potentially break.", select=["padding/double-hedge"], fix=True)
    assert report.fixed_text == "This may break."


# ----- structure ----------------------------------------------------------------------------


def test_bold_lead_bullets_three_in_a_row() -> None:
    three = "- **Speed:** fast\n- **Cost**: free\n- **Support:** email\n"
    assert rules_hit(three, ["structure/bold-lead-bullets"]) == ["structure/bold-lead-bullets"]
    two = "- **Speed:** fast\n- **Cost:** free\n- plain item\n"
    assert rules_hit(two, ["structure/bold-lead-bullets"]) == []
    separated = "- **Speed:** fast\n- **Cost:** free\n\nText.\n\n- **Support:** email\n"
    assert rules_hit(separated, ["structure/bold-lead-bullets"]) == []


def test_same_opener_sentences_and_bullets() -> None:
    s = "Caching reduces load. Caching hides latency. Caching serves stale data."
    assert rules_hit(s, ["structure/same-opener"]) == ["structure/same-opener"]
    ignored = "The cat sat. The dog ran. The bird flew."
    assert rules_hit(ignored, ["structure/same-opener"]) == []
    bullets = "- Run tests\n- Run lint\n- Run build\n"
    assert rules_hit(bullets, ["structure/same-opener"]) == ["structure/same-opener"]


def test_sentence_rhythm_flat_vs_varied() -> None:
    flat = "The cache stores pages. The cache expires them. The cache ignores users. The cache lives there. The cache is optional."
    assert rules_hit(flat, ["structure/sentence-rhythm"]) == ["structure/sentence-rhythm"]
    varied = "The cache stores pages and expires them every hour unless an editor clears them first. Users bypass it. It lives in Redis, which costs us little. Optional. We like it."
    assert rules_hit(varied, ["structure/sentence-rhythm"]) == []


def test_emoji_heading_and_sign_off() -> None:
    assert rules_hit("## 🚀 Start\n", ["structure/emoji-heading"]) == ["structure/emoji-heading"]
    assert rules_hit("## Start 🚀\n", ["structure/emoji-heading"]) == ["structure/emoji-heading"]
    assert rules_hit("Happy coding!", ["structure/sign-off"]) == ["structure/sign-off"]


def test_question_heading_is_off_by_default() -> None:
    assert rules_hit("## What is a proxy?\n") == []
    assert rules_hit("## What is a proxy?\n", ["structure/question-heading"]) == ["structure/question-heading"]


# ----- clarity ------------------------------------------------------------------------------


def test_jargon_and_fix() -> None:
    report = lint_text("Going forward, pick the low-hanging fruit.", select=["clarity/jargon"], fix=True)
    assert report.fixed_text == "From now on, pick the easy wins."


def test_passive_is_opt_in_and_skips_adjectives() -> None:
    text = "The file is read by the parser. We are interested. It was fixed."
    assert rules_hit(text) == []
    hits = texts(text, "clarity/passive")
    assert hits == ["is read"]


def test_long_sentence_limit() -> None:
    long = " ".join(["word"] * 36) + "."
    assert rules_hit(long, ["clarity/long-sentence"]) == ["clarity/long-sentence"]
    assert rules_hit(" ".join(["word"] * 35) + ".", ["clarity/long-sentence"]) == []


def test_nominalisation() -> None:
    assert texts("The implementation of caching led to the reduction of latency.", "clarity/nominalisation") == [
        "The implementation of",
        "the reduction of",
    ]
    assert texts("Read the documentation of the API.", "clarity/nominalisation") == []


def test_double_word_fix_and_exceptions() -> None:
    report = lint_text("Run the the tests. He had had enough.", select=["clarity/double-word"], fix=True)
    assert report.fixed_text == "Run the tests. He had had enough."


def test_readability_opt_in() -> None:
    hard = (
        "The utilisation of asynchronous invocation methodologies necessitates comprehensive reconsideration "
        "of exception-propagation semantics throughout heterogeneous distributed computational infrastructures, "
        "particularly regarding idempotency guarantees and compensating transaction orchestration mechanisms. "
    ) * 2
    assert rules_hit(hard) == [] or "clarity/readability" not in rules_hit(hard)
    assert "clarity/readability" in rules_hit(hard, ["clarity/readability"])


# ----- every rule has docs and examples -------------------------------------------------------


@pytest.mark.parametrize("rule_id", sorted(REGISTRY))
def test_rule_examples_fire_on_before_and_not_after(rule_id: str) -> None:
    r = REGISTRY[rule_id]
    assert r.examples, f"{rule_id} needs an example"
    assert r.why, f"{rule_id} needs a why"
    for ex in r.examples:
        assert rule_id in rules_hit(ex.before, [rule_id]), f"{rule_id} should fire on: {ex.before}"
        if not ex.after.startswith("("):
            assert rule_id not in rules_hit(ex.after, [rule_id]), f"{rule_id} should not fire on: {ex.after}"
