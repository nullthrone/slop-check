# Using the bundled script

The script checks the rule-based patterns of the catalog deterministically: phrase lists,
word lists and measured values. It does not judge the patterns that need reading
comprehension; you judge those. It needs Python 3.10 or newer, uses only the standard library
and never accesses the network.

The skill works without it. If you cannot run commands here, or the script fails, follow
`references/audit-procedure.md` by hand. Do not install anything to make it run.

## Commands

Run the commands from the folder that holds `SKILL.md`, or give the full path to
`scripts/slopcheck.py`. Where `python` is not available, use `python3`.

```
python scripts/slopcheck.py audit FILE [FILE ...] [options]
python scripts/slopcheck.py audit - [options] < FILE
python scripts/slopcheck.py patterns [--modality text|image|web] [--status core|candidate|observation|fading] [--format md|json]
python scripts/slopcheck.py version
```

Options of `audit`:

| Option | Values | Default | Purpose |
|---|---|---|---|
| `--lang` | `de`, `en`, `auto` | `auto` | language of the text |
| `--context` | `default`, `informal`, `technical`, `academic`, `marketing` | `default` | context rules of the thresholds |
| `--format` | `md`, `json` | `md` | report layout or JSON result |
| `--report-lang` | `en`, `de` | `en` | labels of the Markdown report |
| `--fail-on` | `yellow`, `red` | none | exit code 1 when a verdict reaches this level |
| `--catalog` | path | bundled `scripts/catalog.json` | another catalog file |

Exit codes: `0` success (or every verdict below `--fail-on`), `1` a verdict reached
`--fail-on`, `2` usage or input error. Error messages go to standard error.

Do not pass `--llm` in skill mode. It sends the text to an external service, needs an API key
and network access, and duplicates the judgment you do yourself.

## Audit one text

1. If the text exists only in the conversation, save it unchanged to a temporary UTF-8 file,
   or pipe it to standard input with `-`. A file is safer than an echo command for text with
   quotes or line breaks.
2. Run:

   ```
   python scripts/slopcheck.py audit text.md --format json --context technical
   ```

   Pass `--lang` when you know the language better than the detector, for example for a
   short text.
3. Read the JSON result. It has the shape described in `references/report-format.md`, plus
   `short_text`, `not_evaluated_reasons` and per-finding `kind`, `rule`, `unit` and `value`.
4. Judge every pattern listed in `not_evaluated` that has an entry in
   `references/text-patterns.md`, with its rubric, as step 4b of
   `references/audit-procedure.md` describes. Apply its threshold and add triggered ones to
   the findings or observations. IDs without an entry there belong to early-stage patterns
   that are never reported; drop them from `not_evaluated`.
5. Review the script's hits (step 5 of the audit procedure). Remove hits inside quotations of
   others and hits that fall under the pattern's legitimate use. Recheck the threshold of
   each pattern you changed.
6. Recheck patterns with a dependency (the threshold text ends with "only with N other
   findings"). The script sets them as not triggered when too few other patterns triggered;
   your added findings can change that. `all_patterns` shows their hit counts.
7. Recompute score and verdict, then write the report. Remove the judgment patterns from
   `not_evaluated` once you judged them.

## Batch mode

Several files produce one report each. With `--format md`, the reports are separated by a
line `---`. With `--format json`, a single file gives one object and several files give an
array of objects, each with `source` set to its path.

```
python scripts/slopcheck.py audit docs/*.md --format json --fail-on red
python scripts/slopcheck.py audit posts/*.md --report-lang de
```

Batch results contain the rule-based patterns only. Judgment patterns stay under "Not
evaluated" unless you judge them file by file. Say this when you pass batch results on. For
many files, give the user a short table with one row per file (verdict and score) and the
full report only for files that reached YELLOW or RED.

## Pattern list and version

`patterns` prints the catalog as a table or as JSON; `--modality` and `--status` filter it.
`version` prints the engine version and the catalog version together with the number of
patterns. Use that catalog version in the JSON result when you worked by hand.
