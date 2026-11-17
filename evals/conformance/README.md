# Skill conformance cases

`slopcheck-dev conformance --skill dist/slop-check --out FILE` loads the built skill
(`SKILL.md` and `references/*.md`; scripts are left out because the skill must work without
them) into a system prompt and sends every case in `cases/` to each model resolved for the
`conformance` role in `models/lock.json`.

## Case format

One YAML file per case, named after its `id`.

```yaml
id: en-audit-launch-announcement   # unique, equals the file name
language: en                       # en | de (the request is phrased in this language)
mode: audit                        # audit | rewrite
notes: what the case is about
text: |
  The text under test.
# audit cases
must_find: [antithesis-template]   # ids that must appear in findings or observations
must_not_find: [emoji-decoration]  # ids that must not appear
expect_verdict: [RED]              # optional: accepted verdicts
max_findings: 0                    # optional: maximum number of scored findings (clean texts)
# rewrite cases
must_remove: ["In conclusion"]     # phrases that must be gone from the rewritten text
must_keep: ["9 am to 7 pm"]        # facts that must survive (meaning check)
min_length_ratio: 0.4              # rewritten words / original words
max_length_ratio: 1.3
```

Audit replies are scored from the JSON result block of the report
(`skill/references/report-format.md`, shape of `docs/architecture.md` section 4.5). A pattern
counts as found when its id is in `findings` or `observations`. Rewrite replies are asked to
repeat the rewritten text in a fenced block with the info string `rewrite`; the checks run on
that block.

Per model the result reports recall over `must_find`, precision against `must_not_find` plus
any scored findings above `max_findings`, verdict accuracy, the pass rate on clean texts and the
pass rate on rewrite cases.

## Adding a case

Every `must_find` id must trigger in `slopcheck audit` on the case text, and no `must_not_find`
id may trigger, so that the case tests the skill instructions and not the detector. Clean texts
must come out GREEN with no scored findings in `slopcheck audit`. Write case texts yourself;
do not copy published text.
