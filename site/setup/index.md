---
title: Set up slop-check
eyebrow: Setup
lead: Pick your assistant. Each guide lists numbered steps and the official pages it was checked against.
description: Install the slop-check skill in Claude, Gemini, ChatGPT, GitHub Copilot, Microsoft 365 Copilot, Mistral, Cursor, OpenCode, goose or any assistant with a system prompt.
aside: setup
---

## Before you start

Download [slop-check.zip]({{ site.download_zip }}) from the latest release. The archive holds one
folder, `slop-check`, with `SKILL.md` at its top level next to a `references` folder and a
`scripts` folder. Keep the folder name: several runtimes require it to match the skill name.

Runtimes take the package in different shapes:

- The upload dialogs of the Claude apps and Gemini Enterprise take the zip as it is.
- The Gemini app takes the unzipped `slop-check` folder.
- Microsoft 365 Copilot Cowork and Copilot Studio need `SKILL.md` at the root of the archive. The
  [Microsoft guide]({{ '/setup/microsoft/' | relative_url }}) shows how to repack it.
- Command-line agents and editors read the unzipped folder from a skills directory.

Where the runtime can run Python 3.10 or newer, the skill uses its bundled checker for the
rule-based patterns. Where it cannot, the assistant applies the catalog in `references/` by itself.
Both paths produce the same report format.

## Choose your assistant

| Guide | Products | Method |
|---|---|---|
{%- for p in site.data.providers %}
| [{{ p.name }}]({{ p.url | relative_url }}) | {{ p.products }} | {{ p.method }} |
{%- endfor %}

## One folder for several agents

Many coding agents read the shared skills directory `~/.agents/skills/` for personal skills and
`.agents/skills/` inside a project. One copy there serves all of them:

```sh
mkdir -p ~/.agents/skills
unzip slop-check.zip -d ~/.agents/skills
```

On Windows, in PowerShell:

```powershell
Expand-Archive slop-check.zip -DestinationPath "$HOME\.agents\skills"
```

Either command leaves `SKILL.md` at `~/.agents/skills/slop-check/SKILL.md`. The table lists the
folders each agent reads, as documented on the pages linked from its guide.

| Agent | Personal folder | Project folder |
|---|---|---|
| Codex | `~/.agents/skills/` | `.agents/skills/` |
| GitHub Copilot CLI | `~/.agents/skills/`, `~/.copilot/skills/` | `.agents/skills/`, `.github/skills/`, `.claude/skills/` |
| Gemini CLI | `~/.agents/skills/`, `~/.gemini/skills/` | `.agents/skills/`, `.gemini/skills/` |
| Antigravity CLI | `~/.gemini/skills/` | `.agents/skills/` |
| Cursor | `~/.agents/skills/`, `~/.cursor/skills/` | `.agents/skills/`, `.cursor/skills/` |
| OpenCode | `~/.agents/skills/`, `~/.config/opencode/skills/` | `.agents/skills/`, `.opencode/skills/` |
| goose | `~/.agents/skills/` | `.agents/skills/` |
| Mistral Vibe | `~/.agents/skills/`, `~/.vibe/skills/` | `.agents/skills/`, `.vibe/skills/` |
| Claude Code | `~/.claude/skills/` | `.claude/skills/` |

Claude Code and Antigravity CLI do not read `~/.agents/skills/`. Give them their own copy.

## Check that it works

Start a new conversation and send an audit request with a short sample:

```text
Audit this text for slop patterns:

In today's fast-paced world, communication is more important than ever.
It's not just about sending messages, it's about building real connections.
```

The answer should be a report that begins with `# Slop-Check:` and a verdict line such as
`Verdict: RED (score 6.0; yellow from 2.0, red from 5.0)`. The exact score depends on the catalog
version and on how the assistant judges borderline hits. If the assistant replies with general advice and no verdict line, the skill did not load.
Go back to the guide for your assistant and check the step that switches the skill on.
