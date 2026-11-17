# Report format

Use these layouts for all audit and rewrite results, including batch runs. The bundled
script prints the same audit layout, so reports look alike whether you counted by hand or ran
the script.

Write the labels in the language of the conversation: German labels when the user writes
German, English labels otherwise. Pattern names and IDs stay as they appear in the catalog.

## Audit report in Markdown

Layout with English labels:

```
# Slop-Check: <title>

Verdict: <VERDICT> (score <score>; yellow from <yellow>, red from <red>) | <words> words | language: <lang>
<rationale>

## Findings (<n>)
1. <name> (`<pattern-id>`, weight <weight>): <count> hits, threshold <rule>
   > "<quote>" (paragraph <p>)
   Suggestion: <suggestion>

## Observations, not scored (<n>)
1. <name> (`<pattern-id>`, <status>): <count> hits, threshold <rule>
   > "<quote>" (paragraph <p>)

## Not evaluated (<n>)
- `<pattern-id>` (<reason>)

## Notes
- <note>
```

Layout with German labels:

```
# Slop-Check: <Titel>

Gesamtbefund: <BEFUND> (Score <score>; Gelb ab <gelb>, Rot ab <rot>) | <wörter> Wörter | Sprache: <sprache>
<Begründung>

## Befunde (<n>)
1. <Name> (`<pattern-id>`, Gewicht <gewicht>): <anzahl> Treffer, Schwelle <regel>
   > "<Zitat>" (Absatz <p>)
   Vorschlag: <Vorschlag>

## Beobachtungen (nicht gewertet) (<n>)
1. <Name> (`<pattern-id>`, <Status>): <anzahl> Treffer, Schwelle <regel>
   > "<Zitat>" (Absatz <p>)

## Nicht ausgewertet (<n>)
- `<pattern-id>` (<Grund>)

## Hinweise
- <Hinweis>
```

### Line by line

1. Title. Use the file name or the document's own title. Without either, write `text`
   (English) or `Text` (German).
2. Verdict line. `<VERDICT>` is `GREEN`, `YELLOW` or `RED`; with German labels write `GRÜN`,
   `GELB` or `ROT`. Write all scores and weights with at least one decimal, the verdict
   thresholds as well (`2.0`, `2.5`, `3.25`); with German labels use a decimal comma
   (`2,0`). `<words>` is the word count of the analyzed text without code blocks. `<lang>`
   is the language code of the text: `de`, `en`, or `und` when the language is not German or
   English.
3. Rationale. Name up to three findings in report order with their weights:
   `Heaviest findings: Antithesis template (2.5), Triad (rule of three) (1.0).` With German
   labels: `Schwerste Befunde: Antithesis template (2,5), Triad (rule of three) (1,0).` When
   nothing triggered, write `No scored pattern reached its threshold.` or `Kein gewertetes
   Muster hat seine Schwelle erreicht.`
4. Findings. Always present. With zero findings, the next line repeats the sentence from the
   rationale. Order the findings by weight, then by hit count, both descending.
5. Each finding line counts hits (`1 hit`, `2 hits`; German `1 Treffer`, `2 Treffer`). For a
   pattern with a measured value add it before the threshold:
   `3 hits, value 4.2, threshold more than 3 per 500 words`. The threshold is the rule that
   applied to this text once short-text and context rules are taken into account.
6. Quote lines. Indent by three spaces. Show at most three quotes per finding, then
   `(+N more)` or `(+N weitere)`. Collapse line breaks and runs of spaces in a quote to single
   spaces. Cut a quote longer than 160 characters to 159 characters plus `…`. The paragraph
   number counts blocks from 1: paragraphs separated by blank lines, and every heading, list
   item and table row on its own. Code blocks do not count.
7. Suggestion. One line per finding, in the language of the conversation. Propose concrete
   wording for the quoted passage, guided by the pattern's fix. If deleting is the fix, say
   which words to delete.
8. Observations. Only when a candidate or fading pattern triggered. Status words: `candidate`
   or `fading`; German `Kandidat` or `auslaufend`. Show one quote, no suggestion.
9. Not evaluated. Only when you skipped a pattern that applies to the text. Reasons:
   `requires an image judge` (`benötigt eine Bildbewertung`) when you cannot see the image,
   `requires a language model` (`benötigt ein Sprachmodell`) when a script result is passed on
   without your judgment, or a short reason of your own such as `no prompt available`.
10. Notes. Always present, as a list, in this order where they apply:
    - provisional weights: `Some weights are provisional: they apply until the first
      measurement replaces them with measured values.` German: `Einige Gewichte sind
      vorläufig: Sie gelten, bis die erste Messung sie durch gemessene Werte ersetzt.`
    - short text: `Short text (<n> words): short-text thresholds apply.` German:
      `Kurzer Text (<n> Wörter): Es gelten die Schwellen für kurze Texte.`
    - language not detected: `Language not detected: only language-independent patterns ran.`
      German: `Sprache nicht erkannt: Nur sprachunabhängige Muster wurden geprüft.`
    - context, when it is not `default`: `Context: technical.` German: `Kontext: technical.`
    - script hits you dismissed, with the reason in a few words.
    - always last: `Findings describe style patterns. They do not show who or what wrote the
      text.` German: `Die Befunde beschreiben Stilmuster. Sie zeigen nicht, wer oder was den
      Text geschrieben hat.`

### Threshold wording

`references/text-patterns.md` states thresholds in English. With German labels translate
them word for word:

| English | German |
|---|---|
| `min 1 per text` | `mind. 1 pro Text` |
| `min 2 per paragraph` | `mind. 2 pro Absatz` |
| `more than 3 per 500 words` | `mehr als 3 pro 500 Wörter` |
| `min 6.5 per 500 words` | `mind. 6,5 pro 500 Wörter` |
| `min 4 per 1000 words in one paragraph` | `mind. 4 pro 1000 Wörter in einem Absatz` |
| `value > 0.5` | `Wert > 0,5` |
| `value ≥ 2 in one paragraph` | `Wert ≥ 2 in einem Absatz` |
| `at least 3 sentences` | `mind. 3 Sätze` |
| `at least 2 paragraphs` | `mind. 2 Absätze` |
| `at least 100 words` | `mind. 100 Wörter` |
| `only with 3 other findings` | `nur mit 3 weiteren Befunden` |

### Example

```
# Slop-Check: launch-post.md

Verdict: YELLOW (score 3.5; yellow from 2.0, red from 5.0) | 212 words | language: en
Heaviest findings: Antithesis template (2.5), Triad (rule of three) (1.0).

## Findings (2)
1. Antithesis template (`antithesis-template`, weight 2.5): 1 hit, threshold min 1 per text
   > "It's not just a tool — it's a movement" (paragraph 1)
   Suggestion: State the claim directly, for example "The tool syncs drafts across devices."
2. Triad (rule of three) (`triad`, weight 1.0): 3 hits, value 3, threshold min 6.5 per 500 words
   > "fast, secure, and scalable" (paragraph 2)
   > "plan, build and ship" (paragraph 3)
   > "faster, simpler and cheaper" (paragraph 4)
   Suggestion: Keep the one property the reader needs and support it with a number.

## Observations, not scored (1)
1. Rhetorical self-answer (`rhetorical-self-answer`, candidate): 1 hit, threshold min 1 per text
   > "The result? Happier teams." (paragraph 4)

## Notes
- Some weights are provisional: they apply until the first measurement replaces them with measured values.
- Findings describe style patterns. They do not show who or what wrote the text.
```

The same report with German labels:

```
# Slop-Check: launch-post.md

Gesamtbefund: GELB (Score 3,5; Gelb ab 2,0, Rot ab 5,0) | 212 Wörter | Sprache: en
Schwerste Befunde: Antithesis template (2,5), Triad (rule of three) (1,0).

## Befunde (2)
1. Antithesis template (`antithesis-template`, Gewicht 2,5): 1 Treffer, Schwelle mind. 1 pro Text
   > "It's not just a tool — it's a movement" (Absatz 1)
   Vorschlag: Die Aussage direkt treffen, etwa "The tool syncs drafts across devices."
2. Triad (rule of three) (`triad`, Gewicht 1,0): 3 Treffer, Wert 3, Schwelle mind. 6,5 pro 500 Wörter
   > "fast, secure, and scalable" (Absatz 2)
   > "plan, build and ship" (Absatz 3)
   > "faster, simpler and cheaper" (Absatz 4)
   Vorschlag: Die eine Eigenschaft behalten, die zählt, und sie mit einer Zahl belegen.

## Beobachtungen (nicht gewertet) (1)
1. Rhetorical self-answer (`rhetorical-self-answer`, Kandidat): 1 Treffer, Schwelle mind. 1 pro Text
   > "The result? Happier teams." (Absatz 4)

## Hinweise
- Einige Gewichte sind vorläufig: Sie gelten, bis die erste Messung sie durch gemessene Werte ersetzt.
- Die Befunde beschreiben Stilmuster. Sie zeigen nicht, wer oder was den Text geschrieben hat.
```

### Image audits

Use the same layout with these changes. The verdict line ends with `| image` (German
`| Bild`) in place of word count and language. Quote lines describe the visible spot in a few
words without quotation marks and without a paragraph number, for example
`   > left hand of the woman in front: six fingers`. Image patterns carry weight 0 until a
measurement exists, so they appear under observations. Add the note `Image patterns are not
scored yet; the verdict covers scored patterns only.` (German: `Bildmuster werden noch nicht
gewertet; der Gesamtbefund umfasst nur gewertete Muster.`)

## JSON result

Give the JSON result when the user or the calling program asks for JSON:

- If the request asks for JSON only (for example "only JSON", "machine-readable output",
  "return the JSON"), answer with the JSON object alone: no code fence, no text before or
  after it.
- If the request asks for the report together with its JSON result block, write the Markdown
  report first and then the JSON object in one fenced code block with the info string `json`
  at the very end of the answer.
- Otherwise give the Markdown report only.

Shape of the object:

```json
{
  "engine_version": "manual",
  "catalog_version": "2026.11.17",
  "verdict": "YELLOW",
  "score": 3.5,
  "verdict_thresholds": {"yellow": 2.0, "red": 5.0},
  "provisional": true,
  "words": 212,
  "language": "en",
  "context": "default",
  "modality": "text",
  "findings": [
    {
      "pattern_id": "antithesis-template",
      "name": "Antithesis template",
      "effective_status": "core",
      "weight": 2.5,
      "count": 1,
      "triggered": true,
      "threshold": "min 1 per text",
      "hits": [{"quote": "It's not just a tool — it's a movement", "paragraph": 1, "start": null, "end": null}],
      "fix": "State the claim directly, for example \"The tool syncs drafts across devices.\""
    }
  ],
  "observations": [
    {
      "pattern_id": "rhetorical-self-answer",
      "name": "Rhetorical self-answer",
      "effective_status": "candidate",
      "weight": 0.0,
      "count": 1,
      "triggered": true,
      "threshold": "min 1 per text",
      "hits": [{"quote": "The result? Happier teams.", "paragraph": 4, "start": null, "end": null}],
      "fix": ""
    }
  ],
  "not_evaluated": [],
  "all_patterns": {
    "antithesis-template": {"triggered": true, "count": 1},
    "rhetorical-self-answer": {"triggered": true, "count": 1},
    "triad": {"triggered": true, "count": 3}
  }
}
```

The example lists one finding for brevity; a real result lists every finding of the report.

Field rules:

- `verdict` is always `GREEN`, `YELLOW` or `RED` in English, also when the Markdown report
  uses German labels. All numbers are JSON numbers with a decimal point.
- `findings` holds the triggered scored patterns in report order. `observations` holds the
  triggered candidate and fading patterns with `weight` 0. A pattern appears in at most one
  of the two lists.
- `pattern_id` is the catalog ID, never the display name.
- `threshold` is the English threshold text, also in a German report.
- `quote` is an exact substring of the text. `paragraph` is the block number from the report.
  `start` and `end` are character offsets; copy them from the script output, and use `null`
  when you located the passage by hand.
- `fix` holds the suggestion from the Markdown report; it may be empty for observations.
- `not_evaluated` lists the IDs from the "Not evaluated" section.
- `all_patterns` maps pattern IDs to `{"triggered": ..., "count": ...}`. After a script run,
  keep the script's map and update the entries you changed. When you worked by hand, list at
  least every pattern with a hit; patterns you checked without a hit may be added with count 0.
- `engine_version` and `catalog_version`: copy both from the script output. When you worked by
  hand, write `"manual"` and the catalog version named at the top of
  `references/text-patterns.md`.
- `provisional` is `true` when any weight in the score is provisional.
- The script adds more keys, such as `short_text`, `not_evaluated_reasons` and per-finding
  `value`, `rule` and `kind`. Keep them when you pass a script result on.
- For several texts, return a JSON array with one object per text and add `"source"` with
  the file name to each object.
- For an image audit, set `"modality": "image"`, `"words": 0` and `"language": "und"`, and
  write the description of the visible spot into `quote` with `paragraph` `null`.

## Rewrite result

Layout with English labels:

```
# Slop-Check rewrite: <title>

## Rewritten text

<the complete rewritten text>

## Changes (<n>)
1. "<old>" -> "<new>" (`<pattern-id>`): <reason>
2. "<old>" -> (deleted) (`<pattern-id>`): <reason>

## Result
Before: <VERDICT> (score <score>). After: <VERDICT> (score <score>).
<one line on findings that remain, or "No scored pattern remains.">
```

Layout with German labels:

```
# Slop-Check Überarbeitung: <Titel>

## Überarbeiteter Text

<der vollständige überarbeitete Text>

## Änderungen (<n>)
1. "<alt>" -> "<neu>" (`<pattern-id>`): <Grund>
2. "<alt>" -> (gestrichen) (`<pattern-id>`): <Grund>

## Ergebnis
Vorher: <BEFUND> (Score <score>). Nachher: <BEFUND> (Score <score>).
<eine Zeile zu verbleibenden Befunden oder "Kein gewertetes Muster bleibt.">
```

Write the rewritten text as plain Markdown so it reads naturally. If the user asks for a
copyable block, or the text contains Markdown that must survive character for character, put
it in a fenced code block with the info string `rewrite` instead. When the user or the
calling program asks for the rewritten text in a fenced block with a particular info string,
add that block after the result.

Rewrite result as JSON, when JSON is requested:

```json
{
  "mode": "rewrite",
  "language": "de",
  "context": "default",
  "verdict_before": "RED",
  "score_before": 6.0,
  "verdict": "GREEN",
  "score": 0.0,
  "rewritten_text": "...",
  "changes": [
    {"old": "...", "new": "...", "pattern_id": "generic-opening", "reason": "..."}
  ],
  "findings": []
}
```

`verdict`, `score` and `findings` describe the rewritten text after the second audit. For a
deletion, `new` is an empty string.
