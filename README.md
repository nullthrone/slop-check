# slop-check

slop-check is an Agent Skill that finds the stock phrases and rhetorical templates that make
German or English text read like default language-model output, along with typical formatting
habits, and helps remove or avoid them. For images it describes the default look of image
generators and gives prompt rules that steer away from it. Findings name style patterns with
exact quotes and a weighted verdict. They never claim that a text was written by an AI.

## Setup

Download the package: [slop-check.zip](https://github.com/nullthrone/slop-check/releases/latest/download/slop-check.zip).
It contains one folder, `slop-check/`, with `SKILL.md` at its top. Detailed guides per runtime:
[nullthrone.github.io/slop-check/setup](https://nullthrone.github.io/slop-check/setup/).

Claude Code: unzip the package into `~/.claude/skills/` for all your projects, or into
`.claude/skills/` inside a repository to share it with that project. The result is
`~/.claude/skills/slop-check/SKILL.md` (or the project equivalent).

claude.ai: turn on code execution ("Create and edit files" under Settings > Capabilities; on
Enterprise plans an owner enables skills for the organization). Then open Customize > Skills,
click "+", choose "Create skill", then "Upload a skill", and upload `slop-check.zip` as it is.

Gemini app: unzip the package. On gemini.google.com open Customize in the sidebar (under More
if you do not see it), then Skills, Create, Upload, and select the `slop-check` folder. Gemini
applies active skills on its own when a request fits, or you pick one by typing `/` in the chat.
When Google removes Gems, the Gemini app recreates each Gem as a skill. If one of your Gems
already did this job, keep only one of the two active (More > Deactivate).

Gemini CLI: unzip the package into `~/.gemini/skills/` (user) or `.gemini/skills/` (workspace),
or run `gemini skills install ./slop-check` on the unzipped folder. The `.agents/skills/`
directories work as aliases. Gemini CLI asks for consent before it activates a skill.

Other Agent Skills runtimes: many clients scan `.agents/skills/` in the project and
`~/.agents/skills/` in your home directory. Unzip the package there, or wherever your client's
documentation says. The setup guides also cover ChatGPT, Codex, GitHub Copilot, Microsoft 365
Copilot, Mistral, Cursor and other clients.

Runtimes without skill support: download
[system-prompt.md](https://github.com/nullthrone/slop-check/releases/latest/download/system-prompt.md)
and paste it as the system prompt or custom instructions. It is a compact file with the skill
instructions, the report format and a condensed pattern catalog, and it works without file
access or scripts. Where the runtime accepts knowledge files, attach
[knowledge.md](https://github.com/nullthrone/slop-check/blob/dist/exports/knowledge.md) as well:
the full single-file export with every reference and the complete catalog, including all example
phrases, word lists and rubrics.

## What it checks

The catalog lives in [`patterns/`](patterns/), one YAML file per pattern. Each file states the
mechanism and how a detector finds it. A detector is a regular expression or a word list, a
text metric, or a rubric that a language model applies. The file also says when a hit counts,
when the construction is legitimate, how to fix it and how to avoid it while writing.

- Text patterns cover German and English. Some, such as sentence-rhythm metrics, apply to any language.
- Image patterns ship as candidates: the skill reports them and uses their prevention rules for
  image prompts, and they carry no score weight until an image benchmark exists.
- A pattern earns a weight only by measurement: it must fire clearly more often in current model
  output than in human text written before November 2022. [docs/governance.md](docs/governance.md)
  explains the lifecycle.

## Modes

Audit is the default. The skill quotes every finding, counts it against the pattern's threshold
and adds the weights to a score that maps to a traffic-light verdict. Rewrite changes only the
flagged passages and lists each change with the pattern behind it. Prevent applies the rules
while the model writes a text or an image prompt, then checks its own result. Batch runs the
bundled command line tool, which gives the same findings as JSON with an exit code.

## Command line

The package includes a standard-library Python engine. From the skill folder:

```
python scripts/slopcheck.py audit draft.md
python scripts/slopcheck.py audit draft.md --format json --fail-on yellow
python scripts/slopcheck.py audit - --lang de --context marketing --report-lang de < post.txt
python scripts/slopcheck.py patterns --status core
```

Exit codes: 0 when the verdict stays below `--fail-on`, 1 when it reaches it, 2 for usage or input
errors. Patterns that need a language model are listed as not evaluated; the skill judges them
when it runs inside a model.

## Releases and the dist branch

Each GitHub release carries `slop-check.zip`, `system-prompt.md` and `knowledge.md`. The `dist`
branch holds the unpacked package built from the latest `main` and the latest measurement:
`slop-check/` and `exports/` with `system-prompt.md` and `knowledge.md`. Nothing generated is
committed to `main`.

## How measurement works

A monthly workflow measures every text pattern on two corpora that contributors do not control:
human documents published before November 2022 and documents that several current model families
write on the same topics. A pattern that fires much more often in the model output, and rarely in
the human texts, becomes scored core with a weight derived from that ratio. A core pattern that
stops standing out moves to fading. Pull requests pass the same kind of check on a separate split
of the corpora before they merge. Details: [docs/governance.md](docs/governance.md) and
[docs/architecture.md](docs/architecture.md).

## Contributing

Pull requests that add patterns, sources or language realizations merge automatically once the
checks pass. Start with [CONTRIBUTING.md](CONTRIBUTING.md). Questions and false positives go to the
[issue tracker](https://github.com/nullthrone/slop-check/issues). Security reports: [SECURITY.md](SECURITY.md).

## License

[MIT](LICENSE).
