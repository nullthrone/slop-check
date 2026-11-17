"""Text model: units, code masking, sentences, words, language detection."""

from slopcheck.textmodel import (
    build_text_model,
    detect_language,
    mask_code,
    split_sentences,
    word_spans,
)


def unit_texts(model):
    return [(u.kind, model.text[u.body_start : u.end]) for u in model.units]


def sentences(text, lang):
    return [text[s:e] for s, e in split_sentences(text, 0, len(text), lang)]


# --- paragraphs and Markdown units -------------------------------------------------


def test_paragraphs_split_on_blank_lines():
    model = build_text_model("First line\nstill first.\n\n\nSecond paragraph.\n", "en")
    assert unit_texts(model) == [
        ("paragraph", "First line\nstill first."),
        ("paragraph", "Second paragraph."),
    ]
    assert [u.index for u in model.units] == [1, 2]
    assert [u.block for u in model.units] == [0, 1]


def test_headings_list_items_and_table_rows_are_units():
    text = "# Title\nIntro text.\n- one\n- two\n  continued\n1. first\n| a | b |\n|---|---|\n| c | d |"
    model = build_text_model(text, "en")
    assert unit_texts(model) == [
        ("heading", "Title"),
        ("paragraph", "Intro text."),
        ("list_item", "one"),
        ("list_item", "two\n  continued"),
        ("list_item", "first"),
        ("table_row", "| a | b |"),
        ("table_row", "| c | d |"),
    ]
    assert all(u.block == 0 for u in model.units)


def test_horizontal_rule_and_bold_line_are_handled():
    model = build_text_model("Above.\n\n---\n\n**Bold** start is prose.\n\n* * *", "en")
    assert unit_texts(model) == [("paragraph", "Above."), ("paragraph", "**Bold** start is prose.")]


def test_blockquote_body_starts_after_marker():
    model = build_text_model("> Quoted words here.\n> More.", "en")
    unit = model.units[0]
    assert model.text[unit.body_start : unit.end].startswith("Quoted")
    assert model.text[unit.start] == ">"


def test_offsets_point_into_original_text():
    text = "  Leading spaces.\r\n\r\n## Heading  \r\n"
    model = build_text_model(text, "en")
    assert [model.text[u.start : u.end] for u in model.units] == ["Leading spaces.", "## Heading"]
    assert model.line_of(model.units[1].start) == 3


def test_unit_at_and_line_of():
    text = "One.\n\nTwo words."
    model = build_text_model(text, "en")
    assert model.unit_at(0).index == 1
    assert model.unit_at(text.index("Two")).index == 2
    assert model.unit_at(text.index("\n\n") + 1) is None
    assert model.line_of(text.index("Two")) == 3


# --- fenced code ---------------------------------------------------------------------


def test_fenced_code_is_masked_with_same_length():
    text = "Before.\n```python\nx = 'It — is'\n```\nAfter."
    masked = mask_code(text)
    assert len(masked) == len(text)
    assert "It" not in masked
    assert masked.count("\n") == text.count("\n")
    model = build_text_model(text, "en")
    assert unit_texts(model) == [("paragraph", "Before."), ("paragraph", "After.")]


def test_tilde_fence_and_longer_closing_fence():
    text = "~~~~\ncode\n~~~\nstill code\n~~~~~\nProse."
    model = build_text_model(text, "en")
    assert unit_texts(model) == [("paragraph", "Prose.")]


def test_unclosed_fence_runs_to_end():
    model = build_text_model("Prose first.\n\n```\nnever closed\nmore", "en")
    assert unit_texts(model) == [("paragraph", "Prose first.")]
    assert model.word_count == 2


def test_inline_triple_backtick_code_is_not_a_fence():
    """A backtick fence's info string cannot contain backticks (CommonMark), so a line that
    starts with ```code``` is inline code; it must not mask the rest of the text."""
    text = "```npm install``` runs the installer.\n\nThe second paragraph has words."
    assert mask_code(text) == text
    model = build_text_model(text, "en")
    assert unit_texts(model)[-1] == ("paragraph", "The second paragraph has words.")
    assert model.word_count == 10


def test_fence_indented_inside_a_list_item_is_masked():
    text = "1. Step one:\n\n    ```\n    Code here. Code again.\n    ```\n\nAfter code."
    masked = mask_code(text)
    assert len(masked) == len(text) and "Code" not in masked
    model = build_text_model(text, "en")
    assert unit_texts(model) == [("list_item", "Step one:"), ("paragraph", "After code.")]


def test_yaml_front_matter_is_masked():
    text = "---\ntitle: Delve into it\ntags: [a, b]\n---\n\nBody text here."
    masked = mask_code(text)
    assert len(masked) == len(text) and masked.count("\n") == text.count("\n")
    assert "Delve" not in masked and masked.endswith("Body text here.")
    model = build_text_model(text, "en")
    assert unit_texts(model) == [("paragraph", "Body text here.")]
    crlf = "---\r\ntitle: x\r\n---\r\nBody."
    assert unit_texts(build_text_model(crlf, "en")) == [("paragraph", "Body.")]


def test_front_matter_needs_a_closing_line_within_100_lines():
    unclosed = "---\ntitle: x\n\nProse stays."
    assert unit_texts(build_text_model(unclosed, "en"))[-1] == ("paragraph", "Prose stays.")
    late = "---\n" + "key: value\n" * 100 + "---\nProse."
    assert "key" in mask_code(late)
    not_at_start = "Intro.\n\n---\nkey: v\n---\n"
    assert mask_code(not_at_start) == not_at_start


# --- sentences -------------------------------------------------------------------------


def test_english_sentences_and_abbreviations():
    text = "Dr. Smith arrived, e.g. at noon. It rained! Did it? Yes… Then “Quotes” started."
    assert sentences(text, "en") == [
        "Dr. Smith arrived, e.g. at noon.",
        "It rained!",
        "Did it?",
        "Yes…",
        "Then “Quotes” started.",
    ]


def test_no_split_before_lowercase_or_inside_numbers():
    text = "Version 2.5 ships today. see you there. The end."
    assert sentences(text, "en") == ["Version 2.5 ships today. see you there.", "The end."]


def test_german_abbreviations_and_ordinals():
    text = "Das gilt z.B. für Nr. 5 und d.h. Ausnahmen. Der Build schlug am 3. März fehl. Danach lief er."
    assert sentences(text, "de") == [
        "Das gilt z.B. für Nr. 5 und d.h. Ausnahmen.",
        "Der Build schlug am 3. März fehl.",
        "Danach lief er.",
    ]


def test_initials_do_not_end_sentences():
    assert sentences("J. Smith wrote it. Nobody read it.", "en") == ["J. Smith wrote it.", "Nobody read it."]


def test_sentence_after_closing_quote():
    assert sentences('He said "stop." Then he left.', "en") == ['He said "stop."', "Then he left."]


def test_blockquote_lines_do_not_hide_sentence_ends():
    model = build_text_model("> First sentence here.\n> Second sentence here. Third one.", "en")
    unit = model.units[0]
    assert [model.text[s.start : s.end] for s in unit.sentences] == [
        "First sentence here.",
        "Second sentence here.",
        "Third one.",
    ]


def test_unit_sentences_have_word_counts():
    model = build_text_model("One two three. Four five.", "en")
    assert [s.words for s in model.units[0].sentences] == [3, 2]
    assert model.sentence_count() == 2


# --- words ----------------------------------------------------------------------------


def test_words_keep_inner_apostrophes_and_split_underscores():
    text = "It's __bold__ and don’t snake_case."
    words = [text[s:e] for s, e in word_spans(text)]
    assert words == ["It's", "bold", "and", "don’t", "snake", "case"]


def test_markdown_markers_are_not_words():
    model = build_text_model("## Title here\n\n1. First item", "en")
    assert model.word_count == 4


# --- language detection ----------------------------------------------------------------


def test_detects_german():
    assert detect_language("Das ist nicht die Lösung, die wir brauchen, sagte sie.") == "de"


def test_detects_english():
    assert detect_language("It’s ready for review and the team is happy with it.") == "en"


def test_undetermined_for_short_or_neutral_text():
    assert detect_language("Game over.") == "und"
    assert detect_language("Mapping: old_name → new_name, user_id → id.") == "und"
    assert detect_language("") == "und"


def test_mixed_text_below_confidence_is_und():
    assert detect_language("The cat and the dog. Der Hund und die Katze.") == "und"


def test_code_is_ignored_for_detection():
    text = "```\nthe and of to is are with for\n```\nDas ist gut und wir sind froh."
    assert detect_language(text) == "de"


def test_explicit_language_wins_and_region_is_dropped():
    assert build_text_model("The cat and the dog.", "de-DE").language == "de"
    assert build_text_model("The cat and the dog.", None).language == "en"
    assert build_text_model("The cat and the dog.", "auto").language == "en"
