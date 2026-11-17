"""Regex and lexicon detectors, position rules, realization lookup."""

import pytest

from slopcheck.detectors import compile_regexes
from slopcheck.engine import analyze, realization_for


def run(text, pattern, catalog, lang="en", **kwargs):
    result = analyze(text, catalog(pattern), lang=lang, **kwargs)
    return result["all_patterns"][pattern["id"]], result


def finding_hits(result, pattern_id):
    for item in result["findings"] + result["observations"]:
        if item["pattern_id"] == pattern_id:
            return item["hits"]
    return []


# --- regex ---------------------------------------------------------------------------


def test_regex_hits_have_offsets_into_original_text(pattern, catalog):
    p = pattern("rx", realizations={"en": {"patterns": [r"(?i)\bnot just\b[^.]*"]}})
    text = "Intro.\n\nIt is NOT JUST a tool, it is more."
    entry, result = run(text, p, catalog)
    assert entry == {"triggered": True, "count": 1}
    hit = finding_hits(result, "rx")[0]
    assert hit["quote"] == text[hit["start"] : hit["end"]] == "NOT JUST a tool, it is more"
    assert hit["paragraph"] == 2
    assert hit["line"] == 3


def test_regex_quote_is_trimmed_of_whitespace_and_punctuation(pattern, catalog):
    p = pattern("rx", realizations={"en": {"patterns": [r"(?:^|[.!?]\s+)Not\s+\w+,"]}})
    _, result = run("Fine. Not today, thanks.", p, catalog)
    assert finding_hits(result, "rx")[0]["quote"] == "Not today"


def test_regex_multiline_anchor_matches_line_starts(pattern, catalog):
    p = pattern("rx", realizations={"en": {"patterns": [r"^#{1,6}[ \t]+Why\b.*$"]}})
    entry, _ = run("Text first.\n\n## Why it matters\n\n## How it works", p, catalog)
    assert entry["count"] == 1


def test_overlapping_matches_of_several_regexes_count_once(pattern, catalog):
    p = pattern("rx", realizations={"en": {"patterns": [r"not just a tool", r"just a tool"]}})
    entry, _ = run("It is not just a tool.", p, catalog)
    assert entry["count"] == 1


def test_regex_inside_fenced_code_is_ignored(pattern, catalog):
    p = pattern("rx", realizations={"en": {"patterns": [r"not just"]}})
    entry, _ = run("Prose.\n\n```\nnot just code\n```\n", p, catalog)
    assert entry["count"] == 0


def test_invalid_regex_raises_value_error(pattern, catalog):
    p = pattern("broken", realizations={"en": {"patterns": ["(unclosed"]}})
    with pytest.raises(ValueError, match="broken"):
        run("Some text.", p, catalog)


def test_regexes_are_compiled_once(pattern, catalog):
    p = pattern("cached-rx", realizations={"*": {"patterns": [r"\bcached\b"]}})
    run("cached text", p, catalog)
    before = compile_regexes.cache_info().hits
    run("cached text again", p, catalog)
    assert compile_regexes.cache_info().hits > before


# --- positions --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("position", "text", "expected"),
    [
        ("any", "Yes. Indeed it works.", 1),
        ("text_start", "Indeed it works.\n\nIndeed again.", 1),
        ("text_start", "# Title\n\nIndeed it works.", 0),
        ("paragraph_start", "Indeed one.\n\nThen indeed two.\n\n- Indeed three", 2),
        ("paragraph_start", '"Indeed," she said.', 1),
        ("paragraph_end", "Works indeed.\n\nIndeed it works.", 1),
        ("last_paragraph", "Indeed one.\n\nNothing here.\n\nIndeed last.", 1),
        ("last_paragraph", "Indeed one.\n\n## Wrap up\nIndeed last.", 1),
        ("sentence_start", "Yes. Indeed it works, indeed.", 1),
        ("sentence_start", "Dr. Indeed is a name. Fine.", 0),
    ],
)
def test_positions(pattern, catalog, position, text, expected):
    p = pattern("pos", position=position, realizations={"*": {"patterns": [r"(?i)\bindeed\b"]}})
    entry, _ = run(text, p, catalog, lang="und")
    assert entry["count"] == expected


def test_position_applies_to_lexicon(pattern, catalog):
    p = pattern(
        "lex", kind="lexicon", position="paragraph_start", realizations={"en": {"terms": ["moreover"]}}
    )
    entry, _ = run("Moreover, yes.\n\nIt is moreover fine.", p, catalog)
    assert entry["count"] == 1


# --- lexicon -------------------------------------------------------------------------


def test_lexicon_whole_word_case_insensitive(pattern, catalog):
    p = pattern("lex", kind="lexicon", realizations={"en": {"terms": ["realm"]}})
    entry, _ = run("The REALM and realms; in the realm.", p, catalog)
    assert entry["count"] == 2


def test_lexicon_prefix_term(pattern, catalog):
    p = pattern("lex", kind="lexicon", realizations={"en": {"terms": ["delve*"]}})
    entry, _ = run("We delve, delved and it delves. Undelve is not a word.", p, catalog)
    assert entry["count"] == 3


def test_lexicon_multi_word_terms_and_longest_match(pattern, catalog):
    terms = ["ehrlich", "ehrlich gesagt", "ganz ehrlich"]
    p = pattern("lex", kind="lexicon", realizations={"de": {"terms": terms}})
    entry, result = run("Ehrlich\ngesagt war es gut. Ganz ehrlich, ja.", p, catalog, lang="de")
    assert entry["count"] == 2
    assert [h["quote"] for h in finding_hits(result, "lex")] == ["Ehrlich\ngesagt", "Ganz ehrlich"]


def test_lexicon_apostrophe_variants_match(pattern, catalog):
    p = pattern("lex", kind="lexicon", realizations={"en": {"terms": ["let's be clear", "let’s be clear"]}})
    entry, _ = run("Let’s be clear. Let's be clear.", p, catalog)
    assert entry["count"] == 2


def test_lexicon_matches_inside_markdown_emphasis(pattern, catalog):
    p = pattern("lex", kind="lexicon", realizations={"en": {"terms": ["robust"]}})
    entry, _ = run("A _robust_ and **robust** design.", p, catalog)
    assert entry["count"] == 2


def test_lexicon_umlauts(pattern, catalog):
    p = pattern("lex", kind="lexicon", realizations={"de": {"terms": ["atemberaubend*", "maßgeschneidert*"]}})
    entry, _ = run("Ein atemberaubender Blick und maßgeschneiderte Lösungen.", p, catalog, lang="de")
    assert entry["count"] == 2


# --- realization lookup -----------------------------------------------------------------


def test_realization_merges_language_and_star():
    p = {
        "realizations": {"en": {"patterns": ["a"], "examples": {"positive": ["x"]}}, "*": {"patterns": ["b"]}}
    }
    merged = realization_for(p, "en")
    assert merged["patterns"] == ["a", "b"]
    assert merged["examples"] == {"positive": ["x"]}
    assert realization_for(p, "de")["patterns"] == ["b"]
    assert realization_for({"realizations": {"en": {}}}, "de") is None


def test_undetermined_language_runs_only_star(pattern, catalog):
    p = pattern("rx", realizations={"en": {"patterns": [r"\bfoo\b"]}, "*": {"patterns": [r"\bbar\b"]}})
    entry, result = run("foo bar", p, catalog, lang=None)
    assert result["language"] == "und"
    assert entry["count"] == 1


def test_pattern_without_matching_realization_is_listed_untriggered(pattern, catalog):
    p = pattern("de-only", realizations={"de": {"patterns": [r"\bfoo\b"]}})
    entry, _ = run("foo foo", p, catalog, lang="en")
    assert entry == {"triggered": False, "count": 0}
