---
title: Contribute
eyebrow: Community
lead: Patterns enter the catalog through pull requests and leave it through measurement. This page gives the short version of the rules.
description: How to contribute patterns to slop-check, the research-prompt template, and the measurement rules that decide which patterns carry weight.
---

## Where to start

[CONTRIBUTING.md]({{ site.repository_url }}/blob/main/CONTRIBUTING.md) in the repository describes
the workflow: one YAML file per pattern under `patterns/`, one file per source under `sources/`,
and the checks a pull request has to pass. It also points to the research-prompt template, which
lets you run a pattern search with your own assistant and turn the result into a pattern file for a
pull request.

To add a language, add realizations for it to existing patterns. English and German ship today;
patterns marked for any language apply to every text.

## How a pattern moves through the catalog

Every pattern has a status. The lifecycle runs from `observation` to `candidate` to `core`, and a
core pattern can drop to `fading`.

| Status | What it means | Who decides |
|---|---|---|
| `observation` | Noted with at least one source. Not scored. | The contributor |
| `candidate` | At least two independent sources, a detector, and at least two positive and two negative examples per language. Audited, but carries no weight. | The contributor, checked by CI |
| `core` | Measurement shows the pattern is over-represented in AI text. Scored with a measured weight. | Measurement only |
| `fading` | A core pattern that no longer passes the measurement. Weight 0. | Measurement only |

Nobody declares `core` or `fading` in a pattern file. A scheduled measurement compares how often a
pattern triggers in human texts published before November 2022 and in AI text that CI generates
from several model families. A pattern reaches `core` when at most 5 percent of human documents
trigger it, it triggers at least twice as often in AI text overall, and it stays clearly
over-represented in at least two model families. Its weight follows from that ratio. Contributor examples are required, and they are never enough on
their own, because the measurement uses texts the contributor does not choose.

The patterns in the initial core carry provisional weights until the first measurement covers them.
That measurement either replaces the provisional weight or moves the pattern to `fading`.

## Governance in brief

- Content pull requests merge automatically once every check passes. There is no routine review
  queue.
- Changes to the gate itself need the maintainer's review: workflows, the engine, the evaluation
  code, the thresholds and the skill instructions. CODEOWNERS enforces this.
- Language-model calls in CI run under a hard monthly budget that the code enforces.
- A weekly research routine opens pull requests with new findings. They pass the same checks as
  every other contribution.
- Findings describe style. No pattern, report or document in the project claims that a text was
  written by a model.

## Other ways to help

Report a false positive or a missing pattern in the
[issue tracker]({{ site.repository_url }}/issues). Include the text, the language and the report
you got. If you want to support the work, there is a [Ko-fi page]({{ site.kofi_url }}).
