# slop-check

slop-check is an Agent Skill that finds the stock phrases and rhetorical templates that make
German or English text read like default language-model output, along with typical formatting
habits, and helps remove or avoid them. For images it describes the default look of image
generators and gives prompt rules that steer away from it. Findings name style patterns with
exact quotes and a weighted verdict. They never claim that a text was written by an AI.

## Setup

Download the file for your assistant from the latest release. The
[capability matrix](https://nullthrone.github.io/slop-check/setup/) lists every supported product
with the file to use and what the product does with the skill, and links a step-by-step guide for
each. Keep the folder name `slop-check` when you unzip `slop-check.zip`.

| Runtime | File |
|---|---|
| Claude apps, Claude Code, Claude API, Claude Agent SDK | [slop-check.zip](https://github.com/nullthrone/slop-check/releases/latest/download/slop-check.zip), uploaded as it is or unzipped into `~/.claude/skills/` |
| ChatGPT, Codex, OpenAI API | [slop-check.zip](https://github.com/nullthrone/slop-check/releases/latest/download/slop-check.zip), uploaded, or unzipped into `~/.agents/skills/` for Codex |
| Gemini Enterprise, Gemini CLI, Antigravity | [slop-check.zip](https://github.com/nullthrone/slop-check/releases/latest/download/slop-check.zip), uploaded to Gemini Enterprise, or unzipped into `~/.gemini/skills/` (Gemini CLI) or `~/.gemini/config/skills/` (Antigravity) |
| Gemini app | [slop-check-lite.zip](https://github.com/nullthrone/slop-check/releases/latest/download/slop-check-lite.zip) |
| GitHub Copilot | [slop-check.zip](https://github.com/nullthrone/slop-check/releases/latest/download/slop-check.zip), unzipped into `~/.copilot/skills/` or `.github/skills/` |
| Microsoft 365 Copilot Chat, Agent Builder, Copilot Studio | [slop-check-flat.zip](https://github.com/nullthrone/slop-check/releases/latest/download/slop-check-flat.zip) |
| Microsoft 365 Copilot Cowork | [slop-check-lite.zip](https://github.com/nullthrone/slop-check/releases/latest/download/slop-check-lite.zip) |
| Mistral Vibe Work | The files of [slop-check-lite.zip](https://github.com/nullthrone/slop-check/releases/latest/download/slop-check-lite.zip), entered in the skill form |
| Mistral Vibe CLI | [slop-check.zip](https://github.com/nullthrone/slop-check/releases/latest/download/slop-check.zip), unzipped into `~/.vibe/skills/` |
| Cursor, OpenCode, goose, Devin Desktop, Amp, Zed, JetBrains Junie | [slop-check.zip](https://github.com/nullthrone/slop-check/releases/latest/download/slop-check.zip), unzipped into `~/.agents/skills/` |
| Kiro | [slop-check.zip](https://github.com/nullthrone/slop-check/releases/latest/download/slop-check.zip), unzipped into `~/.kiro/skills/` |
| Instruction fields of about 8,000 characters | [instructions.md](https://github.com/nullthrone/slop-check/releases/latest/download/instructions.md), at most 7,500 characters |
| Knowledge or project files | [knowledge.md](https://github.com/nullthrone/slop-check/releases/latest/download/knowledge.md), the full catalog in one file |
| API system messages | [system-prompt.md](https://github.com/nullthrone/slop-check/releases/latest/download/system-prompt.md), about 62,000 characters, too long for typical instruction fields |

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

Each GitHub release carries three packages and three exports: `slop-check.zip` (folder
`slop-check/` with scripts), `slop-check-flat.zip` (`SKILL.md` at the archive root),
`slop-check-lite.zip` (no scripts), `instructions.md` (at most 7,500 characters),
`system-prompt.md` and `knowledge.md`. The `dist` branch holds the unpacked package built from
the latest `main` and the latest measurement: `slop-check/` and `exports/`. Nothing generated
is committed to `main`.

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
