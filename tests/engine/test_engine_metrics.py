"""Metric registry: every metric of section 4.3, its params, defaults and evidence rules."""

import json
from pathlib import Path

import pytest

from slopcheck.engine import analyze
from slopcheck.metrics import METRICS, is_decorative

SCHEMA = Path(__file__).resolve().parents[2] / "schema" / "pattern.schema.json"


def metric_pattern(pattern, name, value=None, params=None, realizations=None, **threshold):
    rule = dict(threshold)
    if value is not None:
        rule["value"] = value
    return pattern(
        name,
        kind="metric",
        metric=name,
        params=params or {},
        threshold=rule,
        realizations=realizations or {"*": {}},
    )


def evaluate(text, p, catalog, lang="en", **kwargs):
    result = analyze(text, catalog(p), lang=lang, **kwargs)
    return result["all_patterns"][p["id"]], result


def hits_of(result, pattern_id):
    for item in result["findings"] + result["observations"]:
        if item["pattern_id"] == pattern_id:
            return [h["quote"] for h in item["hits"]]
    return []


GTE1 = {"op": "gte", "x": 1}


# --- registry ----------------------------------------------------------------------


def test_registry_matches_schema_enum():
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    enum = schema["$defs"]["detector"]["properties"]["metric"]["enum"]
    assert sorted(METRICS) == sorted(enum)


def test_every_metric_documents_its_params_and_unit():
    for spec in METRICS.values():
        assert spec.fn.__doc__ and "params" in spec.fn.__doc__, spec.name
        assert spec.unit in ("sentences", "paragraphs")


def test_unknown_metric_raises(pattern, catalog):
    p = pattern("x", kind="metric", metric="no_such_metric", threshold={"value": GTE1})
    with pytest.raises(ValueError, match="no_such_metric"):
        analyze("Some text.", catalog(p), lang="en")


# --- em_dash_density -----------------------------------------------------------------


def test_em_dash_density_default_per_100_words(pattern, catalog):
    p = metric_pattern(pattern, "em_dash_density", {"op": "gte", "x": 20})
    entry, result = evaluate("One — two — three four five six seven eight nine ten.", p, catalog)
    assert entry["value"] == pytest.approx(20.0)
    assert entry["triggered"]
    assert hits_of(result, "em_dash_density") == ["One — two — three four", "One — two — three four five"]


def test_em_dash_density_per_words_param_and_dash_kinds(pattern, catalog):
    p = metric_pattern(pattern, "em_dash_density", {"op": "gt", "x": 3}, params={"per_words": 500})
    text = "See pages 10–12, the well-known case – as noted — here."
    entry, _ = evaluate(text, p, catalog)
    assert entry["value"] == pytest.approx(2 * 500 / 11)


def test_em_dash_evidence_only_when_value_rule_met(pattern, catalog):
    p = metric_pattern(pattern, "em_dash_density", {"op": "gt", "x": 3}, params={"per_words": 500})
    text = " ".join(["word"] * 300) + " — end."
    entry, _ = evaluate(text, p, catalog)
    assert entry == {"triggered": False, "count": 0, "value": pytest.approx(500 / 301)}


# --- curly_quotes --------------------------------------------------------------------


def test_curly_quotes_counts_all_four_marks(pattern, catalog):
    p = metric_pattern(pattern, "curly_quotes", GTE1)
    entry, _ = evaluate("He said “yes” and ‘no’. It’s fine.", p, catalog)
    assert entry["count"] == 5
    assert entry["value"] == 5


def test_curly_quotes_exempt_language(pattern, catalog):
    p = metric_pattern(pattern, "curly_quotes", GTE1, params={"exempt_languages": ["de"]})
    text = "„Das ist nicht die Lösung“, sagte die Leiterin und ging."
    assert evaluate(text, p, catalog, lang=None)[0] == {"triggered": False, "count": 0, "value": 0}
    assert evaluate(text, p, catalog, lang="en")[0]["count"] == 1


# --- sentence_length_cv ----------------------------------------------------------------

UNIFORM = "\n\n".join(
    [
        "We checked the numbers for every region this quarter. The sales team beat its targets this time.",
        "The product group shipped three releases this quarter. "
        "Each release passed a review with clear rules.",
        "Our hiring plan made steady progress this whole year. "
        "New people finished onboarding much faster now.",
    ]
)
VARIED = "\n\n".join(
    [
        "It broke. Nobody noticed until the morning stand-up when three people deployed the same fix.",
        "The cause was boring. A dependency changed a default timeout from thirty seconds to five seconds.",
        "We pinned it. Next week we add a lockfile check to CI, which takes ninety seconds per run.",
    ]
)


def test_sentence_length_cv_uniform_run_triggers_with_paragraph_evidence(pattern, catalog):
    p = metric_pattern(pattern, "sentence_length_cv", {"op": "lt", "x": 0.2}, params={"run": 3}, min_units=3)
    entry, result = evaluate(UNIFORM, p, catalog)
    assert entry["triggered"]
    assert entry["value"] < 0.2
    assert len(hits_of(result, "sentence_length_cv")) == 3


def test_sentence_length_cv_varied_text_has_no_evidence(pattern, catalog):
    p = metric_pattern(pattern, "sentence_length_cv", {"op": "lt", "x": 0.2}, params={"run": 3})
    entry, _ = evaluate(VARIED, p, catalog)
    assert not entry["triggered"]
    assert entry["count"] == 0
    assert entry["value"] > 0.2


def test_sentence_length_cv_needs_run_paragraphs(pattern, catalog):
    p = metric_pattern(pattern, "sentence_length_cv", {"op": "lt", "x": 0.2})
    two = "\n\n".join(UNIFORM.split("\n\n")[:2])
    assert "value" not in evaluate(two, p, catalog)[0]
    p_run2 = metric_pattern(pattern, "sentence_length_cv", {"op": "lt", "x": 0.2}, params={"run": 2})
    assert evaluate(two, p_run2, catalog)[0]["triggered"]


def test_sentence_length_cv_skips_headings(pattern, catalog):
    p = metric_pattern(pattern, "sentence_length_cv", {"op": "lt", "x": 0.2})
    with_headings = UNIFORM.replace("\n\nThe product", "\n\n## A heading\n\nThe product")
    assert evaluate(with_headings, p, catalog)[0]["triggered"]


ONE_LINERS = "\n\n".join(
    [
        "Free shipping on all orders over fifty dollars.",
        "Easy returns within thirty days of your purchase.",
        "Secure payment with every major credit card.",
        "Friendly support by phone and email every day.",
    ]
)


def test_sentence_length_cv_one_line_paragraphs_form_a_run_by_default(pattern, catalog):
    p = metric_pattern(pattern, "sentence_length_cv", {"op": "lt", "x": 0.2}, params={"run": 3})
    entry, _ = evaluate(ONE_LINERS, p, catalog)
    assert entry["triggered"] and entry["value"] < 0.2


def test_sentence_length_cv_short_paragraphs_break_runs(pattern, catalog):
    params = {"run": 3, "min_sentences_per_paragraph": 2}
    p = metric_pattern(pattern, "sentence_length_cv", {"op": "lt", "x": 0.2}, params=params)
    assert "value" not in evaluate(ONE_LINERS, p, catalog)[0]
    assert evaluate(UNIFORM, p, catalog)[0]["triggered"]
    # a one-line paragraph in the middle splits the run of three two-sentence paragraphs
    parts = UNIFORM.split("\n\n")
    broken = "\n\n".join([parts[0], "Short note here.", parts[1], parts[2]])
    assert "value" not in evaluate(broken, p, catalog)[0]
    # headings are skipped, they do not break a run
    with_heading = "\n\n".join([parts[0], "## A heading", parts[1], parts[2]])
    entry, result = evaluate(with_heading, p, catalog)
    assert entry["triggered"] and len(hits_of(result, "sentence_length_cv")) == 3


# --- emoji_decoration ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("✅ Fast setup\n✅ No configuration\n✅ Works offline", 3),
        ("## 🚀 Start\n\nText.\n\n## 📌 Goals\n\nMore text.", 2),
        ("- ⭐ Benefits\n- ⭐ Pricing", 2),
        ("→ Step one\n→ Step two", 2),
        ("1️⃣ First\n2️⃣ Second", 2),
        ("Thanks for the fix 🙂", 0),
        ("• Plain bullet\n• Another", 0),
        ("Mapping: old → new.", 0),
        ("```\n├── main.py\n🚀 in code\n```", 0),
    ],
)
def test_emoji_decoration(pattern, catalog, text, expected):
    p = metric_pattern(pattern, "emoji_decoration", GTE1)
    assert evaluate(text, p, catalog, lang="und")[0]["count"] == expected


def test_is_decorative_ranges():
    assert is_decorative("✔ done")
    assert is_decorative("👉 look")
    assert not is_decorative("• item")
    assert not is_decorative("├── tree")
    assert not is_decorative("")


# --- markdown_emphasis_density ---------------------------------------------------------


def test_markdown_emphasis_counts_bold_italic_and_headings(pattern, catalog):
    p = metric_pattern(pattern, "markdown_emphasis_density", {"op": "gt", "x": 2})
    text = "## Summary\nHi team, **quick update**: the *new* release is __ready__ and _done_."
    entry, result = evaluate(text, p, catalog)
    assert entry["count"] == 5
    assert entry["value"] == pytest.approx(5 * 100 / 12)
    assert "**quick update**" in hits_of(result, "markdown_emphasis_density")


def test_markdown_emphasis_ignores_list_markers_snake_case_and_math(pattern, catalog):
    p = metric_pattern(pattern, "markdown_emphasis_density", GTE1)
    text = "* item one\n* item two uses my_var_name and 2 * 3 * 4"
    entry, _ = evaluate(text, p, catalog)
    assert entry["value"] == 0
    assert entry["count"] == 0


# --- paragraph_start_ratio ---------------------------------------------------------------


def test_paragraph_start_ratio_uses_realization_terms(pattern, catalog):
    real = {"en": {"terms": ["furthermore", "in addition"]}, "de": {"terms": ["darüber hinaus"]}}
    p = metric_pattern(
        pattern, "paragraph_start_ratio", {"op": "gt", "x": 0.5}, realizations=real, min_units=2
    )
    text = "Intro.\n\nFurthermore, more.\n\n## Heading\n\nIn addition, even more."
    entry, result = evaluate(text, p, catalog)
    assert entry["value"] == pytest.approx(2 / 3)
    assert hits_of(result, "paragraph_start_ratio") == ["Furthermore", "In addition"]
    de_text = "Einleitung.\n\nDarüber hinaus gilt das.\n\nDarüber hinaus auch das."
    assert evaluate(de_text, p, catalog, lang="de")[0]["triggered"]


def test_paragraph_start_ratio_min_units_and_missing_terms(pattern, catalog):
    real = {"en": {"terms": ["furthermore"]}}
    p = metric_pattern(
        pattern, "paragraph_start_ratio", {"op": "gt", "x": 0.5}, realizations=real, min_units=2
    )
    assert not evaluate("Furthermore, one paragraph only.", p, catalog)[0]["triggered"]
    no_terms = metric_pattern(pattern, "paragraph_start_ratio", {"op": "gt", "x": 0.5})
    assert "value" not in evaluate("Furthermore, a.\n\nFurthermore, b.", no_terms, catalog)[0]


# --- nominalization_density ----------------------------------------------------------


def test_nominalization_density_german_defaults(pattern, catalog):
    p = metric_pattern(pattern, "nominalization_density", {"op": "gte", "x": 3}, params={"per_words": 300})
    text = "Die Durchführung der Operationalisierung erfolgt nach Abschluss der Planung."
    entry, result = evaluate(text, p, catalog, lang="de")
    assert hits_of(result, "nominalization_density") == ["Durchführung", "Operationalisierung", "Planung"]
    assert entry["value"] == pytest.approx(3 * 300 / 9)


def test_nominalization_density_params_and_plurals(pattern, catalog):
    params = {"per_words": 100, "min_word_length": 10, "suffixes": {"en": ["tion"]}}
    p = metric_pattern(pattern, "nominalization_density", GTE1, params=params)
    text = "Implementations and optimizations need a nation of attention."
    entry, result = evaluate(text, p, catalog)
    assert hits_of(result, "nominalization_density") == ["Implementations", "optimizations"]
    assert entry["count"] == 2


def test_nominalization_density_language_without_suffixes(pattern, catalog):
    p = metric_pattern(pattern, "nominalization_density", GTE1)
    assert "value" not in evaluate("Organización y planificación.", p, catalog, lang="es")[0]


# --- bullet_bold_lead ----------------------------------------------------------------


def test_bullet_bold_lead_longest_run(pattern, catalog):
    p = metric_pattern(pattern, "bullet_bold_lead", {"op": "gte", "x": 2})
    text = "- **Speed:** fast\n- **Cost**: low\n- plain item\n- **Support:** always\n\n1. __Scope:__ small"
    entry, _ = evaluate(text, p, catalog)
    assert entry["value"] == 2
    assert entry["count"] == 4
    assert entry["triggered"]


def test_bullet_bold_lead_needs_list_items(pattern, catalog):
    p = metric_pattern(pattern, "bullet_bold_lead", {"op": "gte", "x": 2})
    text = "**Speed:** fast.\n\n**Cost:** low.\n\n- Install **pgvector** first.\n- Then run **make**."
    entry, _ = evaluate(text, p, catalog)
    assert entry == {"triggered": False, "count": 0, "value": 0}


def test_bullet_bold_lead_run_ends_at_paragraph(pattern, catalog):
    p = metric_pattern(pattern, "bullet_bold_lead", {"op": "gte", "x": 2})
    text = "- **A:** one\n\nA paragraph in between.\n\n- **B:** two"
    assert evaluate(text, p, catalog)[0]["value"] == 1


# --- triad -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "lang", "expected"),
    [
        ("The platform is fast, secure, and scalable.", "en", 1),
        ("We value honesty, courage or curiosity in our team.", "en", 1),
        ("Die Lösung ist innovativ, transformativ und bahnbrechend.", "de", 1),
        ("Sie hilft beim Planen, Bauen oder Ausliefern.", "de", 1),
        ("We need apples, pears, plums and grapes.", "en", 0),
        ("We moved the cluster, moved the search index to SSD storage and retired the host.", "en", 0),
        ("In summary, this pivotal and robust solution helps.", "en", 0),
        ("Prices rose by 1, 2 and 3 percent.", "en", 0),
    ],
)
def test_triad(pattern, catalog, text, lang, expected):
    p = metric_pattern(pattern, "triad", GTE1)
    assert evaluate(text, p, catalog, lang=lang)[0]["count"] == expected


def test_triad_custom_conjunctions(pattern, catalog):
    p = metric_pattern(pattern, "triad", GTE1, params={"conjunctions": {"de": ["sowie"]}})
    assert evaluate("Wir prüfen Qualität, Tempo sowie Kosten.", p, catalog, lang="de")[0]["count"] == 1
    assert evaluate("Wir prüfen Qualität, Tempo und Kosten.", p, catalog, lang="de")[0]["count"] == 0


def test_triad_short_text_paragraph_scope(pattern, catalog):
    threshold = {
        "scope": "text",
        "value": {"op": "gte", "x": 3},
        "short_text": {"scope": "paragraph", "value": {"op": "gte", "x": 2}},
    }
    p = pattern("triad", kind="metric", metric="triad", params={}, threshold=threshold)
    two_in_one = "It is fast, safe and cheap. Teams plan, build and ship."
    split = "It is fast, safe and cheap.\n\nTeams plan, build and ship."
    entry, _ = evaluate(two_in_one, p, catalog)
    assert entry["triggered"] and entry["value"] == 2
    entry, _ = evaluate(split, p, catalog)
    assert not entry["triggered"] and entry["count"] == 2 and entry["value"] == 1
    long_text = split + "\n\n" + " ".join(["filler"] * 200) + "."
    assert not evaluate(long_text, p, catalog)[0]["triggered"]
    assert evaluate(long_text + " Quick, clean and simple.", p, catalog)[0]["triggered"]


# --- comma_density ---------------------------------------------------------------------


def test_comma_density_ignores_digit_commas(pattern, catalog):
    p = metric_pattern(pattern, "comma_density", {"op": "gt", "x": 0})
    text = "Yes, we did. It cost 2,000 euros at 4,2 percent. Then, finally, it ended."
    entry, result = evaluate(text, p, catalog)
    assert entry["value"] == pytest.approx(3 / 3)
    assert hits_of(result, "comma_density") == ["Then, finally, it ended."]


def test_comma_density_low_evidence_and_min_units(pattern, catalog):
    p = metric_pattern(pattern, "comma_density", {"op": "lt", "x": 0.4}, min_units=3)
    sparse = "We met. We talked. We left. Then, we slept."
    entry, result = evaluate(sparse, p, catalog)
    assert entry["triggered"] and entry["value"] == pytest.approx(0.25)
    assert hits_of(result, "comma_density") == ["We met.", "We talked.", "We left."]
    assert evaluate("We met. We left.", p, catalog)[0] == {"triggered": False, "count": 0, "value": 0}


# --- hyphenated_premodifier_density ------------------------------------------------------


def test_hyphenated_premodifier_density_english(pattern, catalog):
    p = metric_pattern(pattern, "hyphenated_premodifier_density", {"op": "gt", "x": 2})
    text = "Our cloud-native, AI-powered platform is well-known. The side-effect is rare."
    entry, result = evaluate(text, p, catalog)
    assert hits_of(result, "hyphenated_premodifier_density") == ["cloud-native", "AI-powered"]
    assert entry["value"] == pytest.approx(2 * 100 / 14)


def test_hyphenated_premodifier_density_german_noun_compounds_excluded(pattern, catalog):
    p = metric_pattern(pattern, "hyphenated_premodifier_density", GTE1)
    text = "Die KI-gestützte Plattform nutzt das Patch-Release und die Strecke Köln-Bonn ist kurz."
    _, result = evaluate(text, p, catalog, lang="de")
    assert hits_of(result, "hyphenated_premodifier_density") == ["KI-gestützte"]


# --- metric without value rule ------------------------------------------------------------


def test_metric_with_count_rule_uses_hits(pattern, catalog):
    p = pattern("tri", kind="metric", metric="triad", params={}, threshold={"min_count": 2})
    assert not evaluate("It is fast, safe and cheap.", p, catalog)[0]["triggered"]
    assert evaluate("It is fast, safe and cheap. Plan, build and ship.", p, catalog)[0]["triggered"]
