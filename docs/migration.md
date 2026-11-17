# Migration from the legacy knowledge base

Before this repository existed, the catalog lived in a private document series, the "KI-Slop-Wissensbasis". It
was migrated once on 2026-11-17 and then archived (docs/architecture.md, decision D1). From now on the pattern
files under `patterns/` and the git history are the only record of the catalog.

## The legacy knowledge base

The knowledge base was a German-language document series with one dated state per research round. The base
taxonomy is dated 2026-07-30; fourteen updates followed, mostly weekly, from 2026-08-02 to 2026-11-15. Each
state repeated the full catalog and added a change log and a version history. The series was private and is
not publicly reachable. It is archived, and nobody updates it any more.

A state had eight parts: diagnostic principles, a three-tier classification, the core catalog, a traffic-light
matrix for the overall verdict, open candidates (section 5), single-source observation notes (section 5a),
evidence refinements for core patterns (section 6) and a log of confirmations and rejected finds (section 7).
A weekly research routine searched the web for new sources, re-checked the open candidates and wrote the next
state.

Admission worked by counting sources. A candidate was opened at two independent sources. From 2026-08-16 on, a
candidate entered the core at four independent sources, judged by the routine itself. Independence was a
judgement call, and trend labels from a community directory sometimes overrode the count (candidate T2.12 was
held back for a "fading" label although it had four sources).

In this repository the knowledge base appears as the source `legacy-knowledge-base` of type `own-observation`.
It records provenance and never counts toward source independence. External sources that the migrated patterns
cite have their own files under `sources/`. Where the knowledge base noted that one source might copy another,
the source file says so in `derived_from`. URLs and dates were copied only when the knowledge base recorded
them or when they were checked at migration; other source files carry the access note "URL not verified at
migration".

## Legacy ID mapping

Pattern files that descend from a numbered legacy entry keep its ID in `legacy_id`. Grandfathered core
patterns also keep `legacy_tier`, which only selects the bootstrap weight.

| Legacy ID | Legacy name | New pattern id | Status | Note |
|-----------|-------------|----------------|--------|------|
| T1.1 | Antithese-Template | `antithesis-template` | core, provisional | tier 1 |
| T1.2 | Sycophant Residue | `sycophant-residue` | core, provisional | tier 1 |
| T1.3 | Cover-Your-Ass-Disclaimer | `cya-disclaimer` | core, provisional | tier 1; original example group |
| T1.3 | Konzessions-Pivot (example group since 2026-08-16) | `concession-pivot` | core, provisional | tier 1; split out of T1.3 |
| T1.4 | Generic Opening Cliche | `generic-opening` | core, provisional | tier 1 |
| T1.5 | Compulsive Summary | `compulsive-summary` | core, provisional | tier 1 |
| T1.6 | Leere Payoff-Ankündigung | `payoff-announcement` | core, provisional | tier 1 |
| T1.7 | Dramatisches Fragment-Pathos | `fragment-pathos` | core, provisional | tier 1 |
| T2.1 | Triade / Rule of Three | `triad` | core, provisional | tier 2 |
| T2.2 | Em-Dash-Inflation | `em-dash-inflation` | core, provisional | tier 2; dash part of T2.2 |
| T2.2 | Typografie-Artefakte (curly quotes) | `curly-quotes` | core, provisional | tier 2; split out of T2.2 |
| T2.3 | Bullet-with-Bold-Lead | `bullet-bold-lead` | core, provisional | tier 2 |
| T2.4 | AI-Hallmark-Vokabular | `hallmark-vocabulary` | core, provisional | tier 2; absorbs T3.2 |
| T2.5 | Partizip-Auspolsterung am Satzende | `participle-padding` | core, provisional | tier 2 |
| T2.6 | Inflated Importance | `inflated-importance` | core, provisional | tier 2 |
| T2.7 | Tourism-Brochure-Ton | `brochure-tone` | core, provisional | tier 2 |
| T2.8 | False Ranges | `false-range` | core, provisional | tier 2 |
| T2.9 | Deutsche Floskel-Inflation | `german-stock-phrases` | core, provisional | tier 2; German only |
| T2.10 | Rhythmische Gleichförmigkeit | `uniform-rhythm` | core, provisional | tier 2 |
| T2.11 | Nominalisierungs-Dichte | `nominalization-density` | core, provisional | tier 2 |
| T2.12 | Rhetorische Selbstantwort | `rhetorical-self-answer` | candidate | |
| T2.13 | Erfundene Pseudo-Fachbegriffe | `invented-concept-label` | candidate | |
| T2.14 | Punktuations-Sparsamkeit & And-Stacking | `punctuation-sparsity` | candidate | |
| T2.15 | Formal-Transition-Stacking am Absatzanfang | `transition-stacking` | core, provisional | tier 2; core since 2026-09-13 |
| T2.16 | Pseudo-substanzielle Füllsätze / Deletion-Test | `hollow-sentences` | core, provisional | tier 2; core since 2026-09-13 |
| T2.17 | Synonym Cycling | `synonym-cycling` | core, provisional | tier 2; core since 2026-09-20 |
| T2.18 | Leere Verstärker-Adverbien | `empty-intensifiers` | core, provisional | tier 2; core since 2026-09-20 |
| T2.19 | Name Dropping | `name-dropping` | candidate | |
| T2.20 | Reasoning Leak | `reasoning-leak` | observation | legacy candidate; one independence cluster |
| T2.21 | Compulsive Counting | `compulsive-counting` | observation | legacy candidate; one independence cluster |
| T2.22 | Personifizierte Abstraktionen / False Agency | `false-agency` | core, provisional | tier 2; core since 2026-09-27 |
| T2.23 | First-Word Fingerprints | `model-fingerprint-opener` | candidate | |
| T2.24 | Prämodifikations-Verdichtung | `premodifier-stacking` | candidate | |
| T2.25 | Emoji-/Unicode-Dekoration | `emoji-decoration` | core, provisional | tier 2; core since 2026-11-15 |
| T2.26 | Markdown-Emphase-Inflation | `markdown-emphasis-inflation` | candidate | opened 2026-11-15 |
| T3.1 | Vage oder unbelegt-präzise Attribution | `vague-attribution` | core, provisional | tier 3; `requires: {min_other_findings: 3}` |
| T3.2 | Isolierte Hallmark-Vokabeln | `hallmark-vocabulary` | absorbed | no own file |
| 5a | Title Case Headings | `title-case-headings` | observation | |
| 5a | Belaboring the Unnecessary | `belaboring-the-unnecessary` | observation | |
| 5a | Forced Figurative Language | `forced-figurative-language` | observation | |
| 5a | Excessive Enumeration | `excessive-enumeration` | observation | |
| 5a | Fractal Summaries | `fractal-summaries` | observation | |
| 5a | Format Bleed | `format-bleed` | observation | |
| 5a | Premise Stacking | `premise-stacking` | observation | |
| 5a | Preamble (Announce-then-Answer) | `announce-then-answer` | observation | |
| 5a | Self-Echo | `self-echo` | observation | |
| 5a | Appeal to Familiarity | `appeal-to-familiarity` | observation | |
| 5a | "Where/What/Why"-Headers | `where-what-why-headers` | observation | |
| 5a | "Where it actually lives" | `where-it-actually-lives` | observation | |
| 5a | Funktionswort-Verschiebung | `function-word-shift` | observation | English only |
| 5a | Contraction Avoidance / Stiff Formality | `contraction-avoidance` | observation | English only |
| 5a | Bullet-Listen-Präferenz über Fließtext | `bullet-list-preference` | observation | |
| 5a | Noun-Noun-Komposita-Verdichtung / Stacked Nouns | `stacked-nouns` | observation | English only |
| 5a | Grandiose Stakes Inflation | `inflated-importance` | confirmation | no own file; recorded as a confirming source |

Observations from section 5a had no legacy ID and carry none. The two legacy candidates that became
observations keep their legacy IDs so that the mapping stays reversible.

## Changes against the legacy model

### Tiers became attributes

A legacy tier answered three questions at once: when a pattern counts, how much it weighs and whether it
depends on other findings. Decision D3 separates them. The legacy threshold ("Schwelle") became the
`threshold` object, mapped as literally as the schema allows. Weight is measured; until the first measurement
it comes from the legacy tier (see the last section). Dependency became `requires`: T3.1 used to be reported
only alongside at least three exceeded tier-2 patterns and now carries `requires: {min_other_findings: 3}`.
That attribute counts every other triggered scored pattern, tier 1 included, so it is slightly more permissive
than the legacy rule.

### T3.2 absorbed

T3.2 collected single hallmark words below the T2.4 threshold and mentioned them as a side note when a text
was dense with other findings. The engine reports a pattern only once its threshold is reached, and a side
note without a rule cannot be measured. T3.2 therefore has no file; `hallmark-vocabulary` records the change
in its history. Sub-threshold counts remain visible in `all_patterns` of the JSON result.

### T1.3 and T2.2 split

Since 2026-08-16 T1.3 contained two mechanisms. The original disclaimer phrases ("It's important to note that
...") are fixed meta-announcements; the concession pivot ("Despite its challenges, X remains promising")
grants an objection and turns it positive in the same sentence. They need different detectors, and a shared
measurement would hide which of them is over-represented. They are now `cya-disclaimer` and
`concession-pivot`, both with `legacy_id: T1.3` and tier 1.

T2.2 combined em dash density with any occurrence of curly quotes in one OR rule. The two signals have nothing
in common except typography, and curly quotes are correct German typography (low-high quotation marks). They are now
`em-dash-inflation` (metric `em_dash_density`, more than 3 per 500 words) and `curly-quotes` (metric
`curly_quotes` with `exempt_languages: [de]`), both with `legacy_id: T2.2` and tier 2.

### Core is grandfathered and provisional

The 27 patterns listed under `grandfathered_core` in `governance/thresholds.yaml` keep `status: core` with
`provisional: true`. Their core status rested on the legacy source count; nobody had measured them. Until the
first measurement covers a pattern it scores with its bootstrap weight. That measurement then either replaces
the bootstrap weight or demotes the pattern to `fading` (docs/architecture.md, section 5.3). New patterns can
never declare `core`; only measurement derives it.

### Measurement replaces the four-source rule

Decisions D4 and D5 define a slop pattern as one that is over-represented in LLM output relative to a human
baseline. Counting sources still gates the step from observation to candidate, which needs two independent
sources plus a detector with examples (docs/architecture.md, section 3, rule 2). The step from candidate to
core is taken by the scheduled measurement against a human corpus written before November 2022 and an AI
corpus generated by CI, using the thresholds in `governance/thresholds.yaml` (`admission.core`). More sources
no longer promote a pattern, and trend labels from directories carry no weight.

Independence is now mechanical. Two sources belong to the same cluster when one lists the other in
`derived_from` (transitively) or when they share a publisher (section 5.2). This changed two outcomes at
migration. T2.20 and T2.21 each rested on tropes.fyi plus one practitioner skill registered as derived from
tropes.fyi, so each has a single cluster and migrated as an observation. For T2.23 a check of the Search
Engine Journal article showed that it cites the same ICML 2025 study as the skill fork the legacy knowledge
base had counted separately; the article is registered as derived from that study, and the pattern still has
enough clusters to stay a candidate.

### Thresholds set at migration

The legacy knowledge base never found operational thresholds for four of the open candidates (T2.14, T2.19,
T2.24, T2.26), and the section 5a notes had none at all. Where a file needs a threshold, the value was chosen
at migration and the file's `notes` say so. Legacy thresholds that look prone to false positives were copied
faithfully and carry a note as well. Calibration is left to measurement.

### History and rejected finds

Every dated change the knowledge base recorded for a pattern is a `history` entry in that pattern's file,
including sources the research routine checked and rejected. Quantified evidence sits in the `note` of the
source reference. The last history entry of every migrated file is dated 2026-11-17.

## Traffic-light rules and bootstrap weights

The legacy verdict counted findings per tier:

| Legacy verdict | Rule |
|----------------|------|
| GREEN (clean) | 0 tier-1 findings and at most 1 tier-2 finding |
| YELLOW (revise) | 1 tier-1 finding, or 2 to 4 tier-2 findings |
| RED (rewrite paragraphs) | at least 2 tier-1 findings, or at least 5 tier-2 findings, or 1 tier-1 plus at least 3 tier-2 findings |

The new verdict sums the weights of triggered scored patterns and compares the score with two thresholds
(decision D9). Until measurements exist, `governance/thresholds.yaml` sets bootstrap weights by legacy tier
(tier 1: 2.5, tier 2: 1.0, tier 3: 0.5) and verdict thresholds of 2.0 for YELLOW and 5.0 for RED. These values
reproduce the matrix when a finding means a triggered pattern:

| Combination | Score | New verdict | Legacy verdict |
|-------------|-------|-------------|----------------|
| 0 tier-1, 1 tier-2 | 1.0 | GREEN | GREEN |
| 0 tier-1, 2 to 4 tier-2 | 2.0 to 4.0 | YELLOW | YELLOW |
| 1 tier-1, 0 to 2 tier-2 | 2.5 to 4.5 | YELLOW | YELLOW |
| 1 tier-1, 3 tier-2 | 5.5 | RED | RED |
| 0 tier-1, 5 tier-2 | 5.0 | RED | RED |
| 2 tier-1 | 5.0 | RED | RED |

Three cases differ, and they are known:

- The legacy text reported every tier-1 hit individually. If two hits of the same tier-1 pattern counted as
  two findings, the legacy verdict was RED; the score counts the pattern once (2.5, YELLOW).
- T3.1 now adds 0.5 once three other scored patterns of any tier have triggered, while the legacy matrix
  left tier 3 out. One tier-1 plus two tier-2 findings plus vague attribution was YELLOW and now scores 5.0
  (RED).
- The splits can count twice what the legacy model counted once. A text with both disclaimer phrases and a
  concession pivot scores 5.0 (RED) where the legacy model saw one tier-1 pattern; em dashes plus curly
  quotes add 2.0 where the legacy model added one tier-2 finding.

Candidates and observations have weight 0 and never affect the verdict. Once measurements exist, each
pattern's weight becomes `clamp(ln(lift), 0.5, 3.0)`. The verdict thresholds then come from the holdout split:
YELLOW at the 90th percentile of human scores, RED at the median AI score (docs/architecture.md, section 6.4).
Every report marks bootstrap-based scores as provisional.
