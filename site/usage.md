---
title: Usage
eyebrow: Guide
lead: How to ask for each mode and how to read the report. The last section covers the command-line checker.
description: The four slop-check modes with example requests, the report format, and the command-line tool with JSON output and exit codes.
---

slop-check picks its mode from your request. You do not need special syntax; the examples below
show requests that select each mode reliably. The skill understands German requests as well, such
as "Klingt das nach KI?"

## Modes

### Audit

Audit is the default. Use it when you want a text checked or rated. The skill reports and leaves the
text unchanged.

```text
Audit this text for slop patterns:

<paste the text>
```

```text
Does this cover letter sound generic? Check it with slop-check.
```

If you ask whether a text was written by AI, the skill answers that style patterns cannot settle
authorship and offers an audit instead.

### Rewrite

Rewrite changes only the flagged passages, with as little surrounding text as possible. It keeps
the meaning and your voice. Afterwards it audits the result again and returns the cleaned text
with a list of changes.

```text
Rewrite this paragraph to remove the slop findings. Keep my wording where it is fine.
```

A request such as "check this and fix it" runs an audit first and a rewrite after it.

### Prevent

Prevent applies when the assistant writes the text or the image prompt itself. The skill drafts
with the prevention rules, audits its own draft and fixes every scored finding before it answers.
It attaches no report unless you ask for one.

```text
Draft a release announcement for version 2.0 of our invoicing app.
Apply slop-check while you write.
```

For images, prevent mode turns a short request into an art-directed prompt that states:

- the subject and what it is doing
- the setting and the light source
- camera position and composition
- palette and medium

Quality tags and default looks give way to the concrete property they stood for, such as a lens,
a light source or a texture.

```text
Write an image prompt for the header of a blog post about our bakery,
which opens at 5 a.m. Use slop-check prevention.
```

The rules steer away from prompts in the default style:

```text
A beautiful cozy bakery at golden hour, cinematic lighting, hyperrealistic,
8k, masterpiece, trending on artstation
```

An art-directed prompt along the rules:

```text
A baker in a flour-dusted apron slides a tray of rye loaves into a deck oven,
seen from behind the counter at waist height, the baker in the left third of
the frame. Before sunrise: the only light comes from the oven mouth and a cool
fluorescent tube above the workbench. Muted palette of brown, off-white and
steel grey, neutral white balance. 35 mm documentary photograph, fine grain.
```

An explicit wish beats a rule. If you ask for a centered product shot or a glossy 3D style, you get
it.

### Batch

Batch runs the bundled script over several files or a whole folder. It returns one report per
file and sets an exit code; `--format json` switches the output to JSON. It covers the rule-based patterns only; patterns
that need a language model are listed as not evaluated. See [command line](#command-line).

## Context

Some thresholds depend on the kind of text. The skill infers the context from the text and your
request, or uses the one you name: `default`, `informal`, `technical`, `academic` or `marketing`.
For example, "Audit this README, context technical."

## Report format

Reports in the skill and on the command line share one layout. This report is abridged:

```text
# Slop-Check: draft.md

Verdict: RED (score 6.0; yellow from 2.0, red from 5.0) | 48 words | language: en
Heaviest findings: Generic opening cliche (2.5), Antithesis template (2.5), Nominalization density (1.0).

## Findings (3)
1. Generic opening cliche (`generic-opening`, weight 2.5): 2 hits, threshold min 1 per text
   > "In today's fast-paced world" (paragraph 1)
   > "Let's dive in" (paragraph 2)
   Suggestion: Delete the run-up and start with the concrete observation or number that the
   opener was postponing.
2. Antithesis template (`antithesis-template`, weight 2.5): 1 hit, threshold min 1 per text
   > "It's not just about sending messages, it's" (paragraph 1)
   Suggestion: State the claim directly without the negation.
3. ...

## Observations, not scored (1)
1. Premodifier stacking (`premodifier-stacking`, candidate): 1 hit, value 2.0833, threshold value > 2
   > "fast-paced" (paragraph 1)

## Not evaluated (11)
- `hollow-sentences` (requires a language model)
- ...

## Notes
- Short text (48 words): short-text thresholds apply.
- Findings describe style patterns. They do not show who or what wrote the text.
```

The parts of the report:

- The verdict line starts with the verdict and the score, followed by the two thresholds. It ends
  with the word count and the detected language.
- Findings are the triggered scored patterns, heaviest first. Each one shows the pattern ID, its
  weight, the hit count against the threshold, every quote with its paragraph and a suggested fix.
- Observations are triggered patterns that carry no weight yet: candidates and patterns that have
  lost their weight. They do not change the score.
- Not evaluated lists patterns the run could not judge. On the command line these are the patterns
  that need a language model. In the skill, the assistant judges them itself.
- Notes explain conditions that affect the result, such as short-text thresholds.

The score is the sum of the weights of the triggered scored patterns. `GREEN` means the score is
below the yellow threshold. `YELLOW` means it reached the yellow threshold but stayed below the red
one. `RED` means it reached the red threshold. The thresholds of 2.0 and 5.0 are starting values. Once measurement runs, the
yellow threshold is set where 90 percent of human documents score lower, and the red threshold at
the median score of AI documents.

## Command line

The package contains an offline checker for the rule-based patterns. It needs Python 3.10 or newer
and no other packages. Run it from the unzipped `slop-check` folder:

```sh
cd slop-check
python scripts/slopcheck.py audit FILE --format md
python scripts/slopcheck.py audit FILE --format json --fail-on red
```

More examples:

```sh
python scripts/slopcheck.py audit docs/*.md --fail-on yellow     # several files
cat draft.md | python scripts/slopcheck.py audit -               # read from stdin
python scripts/slopcheck.py audit brief.md --lang de --report-lang de
python scripts/slopcheck.py patterns --modality text --status core
python scripts/slopcheck.py version
```

| Option | Values | Effect |
|---|---|---|
| `--format` | `md`, `json` | Markdown report (default) or JSON result |
| `--fail-on` | `yellow`, `red` | Exit with code 1 when a file reaches this verdict |
| `--lang` | `de`, `en`, `auto` | Language of the text; `auto` detects it |
| `--context` | `default`, `informal`, `technical`, `academic`, `marketing` | Context for context-dependent thresholds |
| `--report-lang` | `en`, `de` | Language of the report labels |
| `--catalog` | path | Use another `catalog.json` |
| `--llm` | flag | Also evaluate language-model patterns through OpenRouter; needs `OPENROUTER_API_KEY` |

Exit codes:

| Code | Meaning |
|---|---|
| `0` | Finished, and no file reached the `--fail-on` verdict |
| `1` | At least one file reached the `--fail-on` verdict |
| `2` | Usage or input error, such as a missing file |

The JSON result has this shape (abridged):

{% raw %}
```json
{
  "engine_version": "0.1.0",
  "catalog_version": "2026.11.17",
  "verdict": "RED",
  "score": 6.0,
  "verdict_thresholds": {"yellow": 2.0, "red": 5.0},
  "words": 48,
  "language": "en",
  "context": "default",
  "modality": "text",
  "findings": [
    {
      "pattern_id": "generic-opening",
      "name": "Generic opening cliche",
      "effective_status": "core",
      "weight": 2.5,
      "count": 2,
      "triggered": true,
      "threshold": "min 1 per text",
      "hits": [{"quote": "In today's fast-paced world", "paragraph": 1, "start": 0, "end": 27}],
      "fix": "Delete the run-up and start with the concrete observation ..."
    }
  ],
  "observations": [],
  "not_evaluated": ["hollow-sentences"],
  "all_patterns": {"announce-then-answer": {"triggered": false, "count": 0}}
}
```
{% endraw %}

The field `provisional` is true while any scored weight is still a starting value rather than a
measured one.

In CI, call the script by its path and let the exit code fail the job:

```sh
python path/to/slop-check/scripts/slopcheck.py audit docs/*.md --fail-on red
```
