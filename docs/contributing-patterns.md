# Adding a pattern or a language

This guide walks through a new pattern, a new language realization for an existing pattern, and
the checks to run before you open a pull request. Field definitions: [architecture.md](architecture.md),
section 3, and [`schema/pattern.schema.json`](../schema/pattern.schema.json). Admission rules:
[governance.md](governance.md).

## 1. Check that the pattern is new

Search [`patterns/`](../patterns/) for the mechanism, not only for the name. If an existing
pattern covers the same construction, your evidence is a source for that pattern, and your
pull request adds the source and maybe more examples to the existing file.

## 2. Register the sources

Every source is a file `sources/<id>.yaml` (schema: [`schema/source.schema.json`](../schema/source.schema.json)).
Reuse an existing file when the source is already registered.

```yaml
id: example-corpus-study          # kebab-case, equals the file name
title: "Title as the publisher shows it"
url: https://example.org/study
publisher: Example Lab
authors: ["A. Author"]            # optional
published: 2026-09-01             # or null if the page shows no date
accessed: 2026-11-17
type: corpus-study                # academic-preprint | peer-reviewed | corpus-study | commercial-study |
                                  # community-directory | practitioner-skill | blog | press |
                                  # documentation | own-observation
derived_from: []                  # ids of sources this one copies or summarizes
notes: >
  What the source measured and how (corpus size, languages, models), and any caveat.
```

Two sources from the same publisher, or one derived from the other, count as one independent
source. A `candidate` needs two independent sources; an `observation` needs one.

## 3. Write the pattern file

Create `patterns/<modality>/<id>.yaml`. The id is kebab-case, at most 64 characters, equal to the
file name and never changes after the merge. New patterns declare `status: observation` or
`status: candidate`. The file below follows the reference pattern
`patterns/text/antithesis-template.yaml`, with the status and sources a new candidate would declare.

```yaml
id: antithesis-template
modality: text                    # text | image (code, audio, video are reserved)
name: Antithesis template
summary: >
  Negative parallelism that simulates depth by first denying a claim nobody made and then
  asserting the "real" point ("It's not just X, it's Y"). Used once as a deliberate contrast it
  is ordinary rhetoric; produced reflexively it signals template writing.
category: rhetoric                # see the category list in the schema
status: candidate                 # observation | candidate
detector:
  kind: regex                     # regex | lexicon | metric | llm | vision
  position: any                   # any | text_start | paragraph_start | paragraph_end |
                                  # last_paragraph | sentence_start
threshold:
  min_count: 1                    # hits needed to trigger
  comparison: gte                 # gte | gt
  scope: text                     # text | paragraph
requires: null                    # {min_other_findings: 3} if it only counts alongside others
realizations:
  en:
    patterns:
      - '(?i)\b(?:it[’'']?s|it is|this is|that[’'']?s|that is)\s+not\s+(?:just|only|merely|simply)\b[^.!?\n]{1,80}?[,;:—–-]\s*(?:it[’'']?s|it is|but)\b'
      - '(?i)\bnot\s+only\s+(?:does|do|did|is|are|was|were|can|will)\b[^.!?\n]{1,80}?[;,]\s*(?:it|they|this)\b'
      - '(?i)\b(?:isn[’'']?t|is not|aren[’'']?t|are not)\s+(?:just\s+|merely\s+|simply\s+)?about\s+[^.!?\n]{1,60}?[.;,—–-]\s*(?:it[’'']?s|it is|they[’'']?re|they are|this is)\s+about\b'
      - '(?i)\bnot\s+because\b[^.!?\n]{1,80}?,\s*but\s+because\b'
    examples:
      positive:
        - "It's not just a tool — it's a movement."
        - "This isn't about technology. It's about trust."
        - "Not only does it cut costs; it reshapes how teams work."
      negative:
        - "The fix is not in the parser but in the tokenizer, see issue #12."
        - "Not only the CPU but also the GPU was throttled during the test."
        - "It is not clear whether the patch landed before the freeze."
  de:
    patterns:
      - '(?i)\b(?:es|das|dies)\s+ist\s+(?:nicht\s+(?:nur|bloß|einfach)|kein(?:e|en)?)\s+[^.!?\n]{1,80}?[,;:—–-]\s*(?:es|das|dies)\s+ist\b'
      - '(?:^|[.!?]\s+)Nicht\s+[^.!?,\n]{1,60},\s*sondern\b'
      - '(?i)\bweniger\s+(?:aus|um)\b[^.!?\n]{1,60}?\bals\s+(?:vielmehr\s+)?(?:aus|um)\b'
    examples:
      positive:
        - "Das ist kein Werkzeug, das ist eine Haltung."
        - "Nicht die Technik entscheidet, sondern die Kultur."
        - "Es ist nicht nur ein Update – es ist ein Neuanfang."
      negative:
        - "Das Problem liegt nicht am Parser, sondern am Tokenizer."
        - "Die Messung zeigt keine Regression; der Durchsatz bleibt bei 4,2 GB/s."
        - "Es ist nicht nötig, den Dienst neu zu starten."
legitimate_use: >
  A single, substantive correction of a misconception the reader actually holds ("The outage was
  not caused by the update but by an expired certificate") is not slop. Flag the reflexive form:
  the denied claim is a strawman and the sentence would lose nothing if it only stated the second half.
fix: >
  State the claim directly without the negation. If a real misconception exists, name it and
  give the evidence that refutes it.
prevention: >
  Do not build sentences of the form "not X, but Y" or "it's not just X, it's Y" unless you are
  correcting a misconception the reader demonstrably holds. State the point directly.
sources:
  - source: tropes-fyi
    locator: "entry 'Negative parallelism'"
  - source: pangram-signs-of-ai-writing
    locator: "'not just X but Y' construction"
    note: "Reported at 3x the human baseline (commercial corpus, methodology not disclosed)."
related:
  - {id: german-stock-phrases, relation: overlaps}   # overlaps | distinct-from | supersedes |
                                                     # split-from | merged-into
```

### Choosing a detector

| Kind | Payload | Use it when |
|------|---------|-------------|
| `regex` | `realizations.<lang>.patterns`, Python `re` syntax, compiled with `re.MULTILINE` | The construction has a recognizable surface form. |
| `lexicon` | `realizations.<lang>.terms`, whole words, case-insensitive, `term*` matches a prefix | The signal is a set of words or fixed phrases. |
| `metric` | `detector.metric` and `detector.params` | The signal is a rate or a distribution, such as dash density or sentence-length variation. Only the metrics listed in the schema exist; a new metric needs an engine change. |
| `llm` | `detector.rubric`, plus the examples | Recognizing the pattern needs judgment about meaning. Write the rubric in English and say what does not count. |
| `vision` | `detector.rubric` | Image patterns. Describe what to look at and what does not count. |

Keep regular expressions precise. A pattern that fires on ordinary sentences fails the gate
on the human corpus. Write quoted strings in YAML single quotes, accept the typographic
apostrophe (U+2019) wherever you accept the straight one, and avoid nested unbounded quantifiers such as `(a+)+`:
validation rejects them and times every expression on a 50 kB adversarial input.

### Choosing a threshold

`threshold` says when the hits count. `min_count` with `comparison` sets the number of hits;
`per_words` turns it into a density per that many words; `scope: paragraph` triggers when a single
paragraph reaches the count. Metrics compare their value with `value: {op: gt, x: 3}` and can
require `min_units` sentences or paragraphs. `short_text` overrides the rule for texts of up to 150
words, and `context_overrides` adjusts it for the contexts `informal`, `technical`, `academic`
and `marketing`.

### Examples

Each language needs at least two positive and two negative examples for a candidate. Three to five
of each work better. Positive examples show the pattern as models produce it. Negative examples
are near misses: legitimate sentences that a careless detector would flag, in the same language
and register. Unrelated sentences prove nothing. Optional `test_texts` check the full threshold on
longer passages: `{text: "...", expect: trigger}` or `expect: no_trigger`.

## 4. Adding a language to an existing pattern

Add a key with the language subtag under `realizations` (`fr`, `es`, ...) with the detector payload
for that language (`patterns` or `terms`) and its examples. For a metric with language-specific
parameters, add the language to `detector.params` as well. Collect phrases from texts written in
that language; literal translations of English phrases rarely match what models write there.
Language-agnostic realizations use the key `*`.

## 5. Run the checks

```
pip install -e ".[dev]"
slopcheck-dev validate
slopcheck-dev check-fixtures            # or: slopcheck-dev check-fixtures <id> ...
pytest
```

`validate` checks the schema and the rules of architecture.md section 3 (sources resolve,
independent sources, regex safety, unique terms, file names). `check-fixtures` runs every
positive and negative example through the engine. Patterns with `llm` or `vision` detectors are
listed as skipped there; the LLM gate judges them in the pull request.

If you edit a pattern that scores today (one listed under `initial_core` in
`governance/thresholds.yaml`, or one the measurement made core), run
`slopcheck-dev guard --base origin/main` as well. It fails when the change deletes or renames the
file or changes its status, modality or detector kind; such changes need a maintainer (see
[governance.md](governance.md), "Pull request gate"). Edits to its thresholds, examples, regular
expressions, word lists and rubric are fine; the gates measure them.

Once branch `data` holds a corpus, you can run the empirical gate locally as well:

```
slopcheck-dev corpus fetch-human --out .corpus/human
git fetch origin data
mkdir -p .corpus/data && git archive origin/data corpus | tar -x -C .corpus/data
slopcheck-dev measure --human .corpus/human --ai .corpus/data/corpus/ai --split dev \
    --patterns <id> --out .eval-out/dev.json --report .eval-out/dev.md
slopcheck-dev gate --measure .eval-out/dev.json --patterns <id>
```

## 6. Open the pull request

Fill in the pull request template. The `ci` run posts the empirical gate table in its job summary.
For `llm` patterns the `llm-gate` status, posted once `ci` has passed, links to a run with the
example results, and the pull request receives one comment that is updated on every push. When both required checks pass and
the change touches only `patterns/`, `sources/` or `docs/` (except architecture.md, governance.md
and maintainers.md), the pull request merges by itself.
