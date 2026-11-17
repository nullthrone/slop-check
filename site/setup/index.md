---
title: Set up slop-check
eyebrow: Setup
lead: Pick your assistant. The capability matrix shows which file each product needs and what it does with the skill. Each guide lists numbered steps and the official pages it was checked against.
description: Install the slop-check skill in Claude, Gemini, ChatGPT, Codex, GitHub Copilot, Microsoft 365 Copilot, Mistral Vibe, Cursor and other agents, or use the single-file exports where a product has no skills.
aside: setup
---

## Which file do I need?

Every file is attached to the [latest release]({{ site.releases_url }}/latest).

| File | Contents | Use it for |
|---|---|---|
| [slop-check.zip]({{ site.download_zip }}) | Folder `slop-check/` with `SKILL.md`, `references/` and `scripts/` | Products that take a skill folder or a zip with the folder inside: the Claude apps, Claude Code and the Claude API, ChatGPT, Codex and the OpenAI API, Gemini Enterprise, Gemini CLI, Antigravity, GitHub Copilot, the Vibe CLI and the [other runtimes]({{ '/setup/other-runtimes/' | relative_url }}) |
| [slop-check-flat.zip]({{ site.download_flat_zip }}) | The same files with `SKILL.md` at the root of the archive | Microsoft 365 Copilot Chat, Agent Builder, Copilot Studio |
| [slop-check-lite.zip]({{ site.download_lite_zip }}) | `SKILL.md` and `references/` at the root, no scripts | Microsoft 365 Copilot Cowork, the Gemini app, Vibe Work |
| [instructions.md]({{ site.download_instructions }}) | Compact instructions, at most 7,500 characters | Instruction fields of about 8,000 characters |
| [knowledge.md]({{ site.download_knowledge }}) | Skill instructions and the complete catalog in one file | Knowledge files and project files |
| [system-prompt.md]({{ site.download_prompt }}) | Skill instructions, report format and a condensed catalog, about 62,000 characters | API system messages and large fields; it does not fit typical instruction fields |

When you unzip `slop-check.zip`, keep the folder name `slop-check`: several runtimes require it to
match the skill name. The packaged `SKILL.md` contains the core pattern list and the report layout,
so an audit works from that file alone. Where the runtime can run Python 3.10 or newer, the skill
also uses its bundled checker for the rule-based patterns. Both paths produce the same report
format. The [no-skill guide]({{ '/setup/no-skill-support/' | relative_url }}) explains the three
single-file exports.

## Choose your assistant

| Guide | Products | Method |
|---|---|---|
{%- for p in site.data.providers %}
| [{{ p.name }}]({{ p.url | relative_url }}) | {{ p.products }} | {{ p.method }} |
{%- endfor %}

## Capability matrix

The tables show what each product does with the skill, as its vendor documents it. "Unverified"
means that no official source confirms the statement. "None documented" means that the vendor
names no way to do it. The guide for each product links its sources.

### Anthropic

| Product | Package | Picked automatically | Explicit call | Scripts run | Reference files read | Notes |
|---|---|---|---|---|---|---|
| Claude apps (claude.ai, desktop, Cowork, Office add-ins) | `slop-check.zip`, uploaded as it is | Yes | Name the skill in the request | Yes, in the code-execution container | Yes, on demand | Code execution must be on. The upload also reaches Cowork on mobile and Claude Code signed in with the same account (v2.1.273 or later). Upload from mobile is not documented. |
| Claude Code | `slop-check.zip`, unzipped into `~/.claude/skills/` or `.claude/skills/` | Yes | `/slop-check` | Yes, with the local Python; asks before Bash unless pre-approved | Yes | Claude Code on the web reads the repository copy and skills from claude.ai, not `~/.claude/skills/`. |
| Claude API | `slop-check.zip`, uploaded to `/v1/skills` | Yes | None documented | Yes: Python 3.11, no network | Yes | Separate from claude.ai uploads. Up to 20 skills per request. |
| Claude Agent SDK | `slop-check.zip`, unzipped into `.claude/skills/` | Yes | `/slop-check` in the prompt | Yes, when Bash is allowed | Yes, through Read or Bash | Sessions with an API key get no skills from claude.ai. |

### Google

| Product | Package | Picked automatically | Explicit call | Scripts run | Reference files read | Notes |
|---|---|---|---|---|---|---|
| Gemini app | `slop-check-lite.zip` | Yes, for active skills | `/` (or `@`), then pick the skill | No (observed; Google does not document it) | On demand, when Gemini decides to | Upload only on gemini.google.com and in the Mac app. Mobile apps can use the skill. |
| Gemini Enterprise | `slop-check.zip` | Yes | `@` or `/` mention, or "Use the slop-check skill" | Yes, Python and Bash; runtime version and network unverified | Yes, on demand | An administrator turns skills on. Skills do not work together with agents. |
| Gemini CLI | `slop-check.zip`, unzipped into `~/.gemini/skills/` or `~/.agents/skills/` | Yes, after a consent prompt | None documented | Yes, locally, after approval | Yes, on demand | Workspace skills load only in trusted folders. |
| Antigravity CLI, App and IDE | `slop-check.zip`, unzipped into `~/.gemini/config/skills/` (all three) or `~/.gemini/skills/` (CLI only) | Yes | `/slop-check` | Yes, locally | Yes, as needed | Project skills go in `.agents/skills/`, not `.gemini/skills/`. |
| Gemini API managed agents | Folder from `slop-check.zip`, mounted at `.agents/skills/slop-check/` | Yes | None documented | Yes, in the sandbox | Yes | Preview. Network follows the sandbox's egress allowlist. |
| Agent Platform Skill Registry | `slop-check.zip` | Yes | None documented | Unverified | Unverified | For developers. Zip up to 10 MB. |
| Gemini API without agents | `system-prompt.md` as the system instruction | n/a | n/a | No | n/a | The API has no skills. |
| Google Workspace Studio | Not supported | n/a | n/a | No | n/a | Its skills take no attached files, and Gemini app skills do not appear there. |

### OpenAI

| Product | Package | Picked automatically | Explicit call | Scripts run | Reference files read | Notes |
|---|---|---|---|---|---|---|
| ChatGPT (web and mobile, Chat and Work) | `slop-check.zip` | Yes | `@slop-check` | Unverified | Unverified | OpenAI does not document the upload format; a zip with one root folder is reported to work. OpenAI's pages disagree on which plans can upload. The desktop app keeps its own skills. |
| ChatGPT projects | `instructions.md` in the instructions, `knowledge.md` as a project file | n/a | n/a | No | `knowledge.md`, found by search | Project instructions take about 8,000 characters (user reports). |
| Codex CLI and IDE extension | `slop-check.zip`, unzipped into `~/.agents/skills/` or `.agents/skills/` | Yes | `$slop-check` or `/skills` | Yes, in the sandbox, network off by default | Yes, when needed | Codex Cloud reads only skills committed to the repository. Restart Codex if the skill does not appear. |
| OpenAI API | `slop-check.zip`, uploaded to `/v1/skills` | Yes | None documented | Yes; hosted containers have no outbound network by default | Yes | Zip up to 50 MB and 500 files. |
| OpenAI Agents SDK | Folder from `slop-check.zip`, mounted with the sandbox `Skills` capability | Yes, from an index and the `load_skill` tool | None documented | Depends on the sandbox you configure | Yes | Sandbox agents only. |

### Microsoft

| Product | Package | Picked automatically | Explicit call | Scripts run | Reference files read | Notes |
|---|---|---|---|---|---|---|
| GitHub Copilot CLI | `slop-check.zip`, unzipped into `~/.copilot/skills/` or `.github/skills/` | Yes | `/slop-check` | Yes; asks before the shell tool runs | Yes | Also reads `~/.agents/skills/`. |
| VS Code agent mode | `slop-check.zip`, unzipped into `~/.copilot/skills/` or `.github/skills/` | Yes | `/` in the chat input | Yes, through the terminal tool | On demand | The folder depends on the agent harness. |
| Copilot cloud agent | `slop-check.zip`, unzipped into `.github/skills/` and committed | Yes | Slash commands on github.com | Unverified (Python availability) | Yes | Personal skills only in cloud sandbox sessions, from the dotfiles repository. |
| Copilot code review | The committed copy in `.github/skills/` | Yes, if relevant to the review | None documented | Unverified | Unverified | Reads only `.github/skills/`. |
| Microsoft 365 Copilot Chat | `slop-check-flat.zip` | Yes, with the per-skill toggle on | Select the installed skill | Yes, in a sandbox without network; Python version unverified | Yes | Not supported with Purview Information Barriers. |
| Agent Builder | `slop-check-flat.zip` | Yes | None documented | Yes, in a sandbox without network | Yes | Up to 8 skills per agent. |
| Copilot Studio | `slop-check-flat.zip` | Yes | None documented | Unverified | Unverified | Microsoft Copilot harness only. Whether the zip needs `SKILL.md` at its root is unverified. |
| Microsoft 365 Copilot Cowork | `slop-check-lite.zip` | Yes | None documented in conversations | Documented, but the lite package has no scripts | Yes, on demand | At most 20 files besides `SKILL.md` and 50 custom skills. Not on mobile. |

### Mistral

| Product | Package | Picked automatically | Explicit call | Scripts run | Reference files read | Notes |
|---|---|---|---|---|---|---|
| Vibe Work (formerly Le Chat) | Files of `slop-check-lite.zip`, entered in the skill form; `instructions.md` if the form takes text only | Yes | `/slop-check`, the `/` picker or the skill's name | Unverified; do not attach `scripts/` | Yes, as needed | No package import. The number of supporting files is limited. |
| Vibe Chat | Not supported; use a Work skill | n/a | n/a | n/a | n/a | Custom instructions are meant to be short, and active skills override them. |
| Vibe CLI | `slop-check.zip`, unzipped into `~/.vibe/skills/` or `~/.agents/skills/` | Yes | `/slop-check` | Yes, through Bash; asks first by default | Unverified | Use version 2.25.4 or later. |

### Other runtimes

| Product | Package | Picked automatically | Explicit call | Scripts run | Reference files read | Notes |
|---|---|---|---|---|---|---|
| Cursor | `slop-check.zip`, unzipped | Yes | `/slop-check` | Yes, under Cursor's run modes | On demand | Descriptions can be trimmed when many skills are installed; call `/slop-check` for reliable use. |
| OpenCode | `slop-check.zip`, unzipped | Yes, through the `skill` tool | `@slop-check` | Unverified | Not loaded automatically; the model gets up to ten file paths | Permission rules can deny a skill. |
| goose | `slop-check.zip`, unzipped | Yes | Name it, or `/skills` | Through the Developer extension, without a prompt in the default Autonomous mode | Yes, with the Developer extension's file tools | Skills extension on by default. |
| Devin Desktop | `slop-check.zip`, unzipped | Yes | `/slop-check` | Unverified | Yes, when invoked | Formerly Windsurf. |
| Amp | `slop-check.zip`, unzipped | Yes | None documented | Unverified | Yes, by relative paths | |
| Zed | `slop-check.zip`, unzipped | Yes, through the `skill` tool | `/` or an `@` mention | Unverified | On demand | Zed Agent only. Asks before a skill you installed runs. |
| JetBrains Junie | `slop-check.zip`, unzipped | Yes | `/slop-check` or `$slop-check` | Yes, as needed; approval not stated | On demand | |
| Kiro | `slop-check.zip`, unzipped into `~/.kiro/skills/` | Yes | `/slop-check` | Unverified | When the instructions direct it | Does not document `.agents/skills/`. |

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
| Cursor | `~/.agents/skills/`, `~/.cursor/skills/` | `.agents/skills/`, `.cursor/skills/` |
| OpenCode | `~/.agents/skills/`, `~/.config/opencode/skills/` | `.agents/skills/`, `.opencode/skills/` |
| goose | `~/.agents/skills/` | `.agents/skills/` |
| Devin Desktop | `~/.agents/skills/`, `~/.config/devin/skills/` | `.agents/skills/`, `.devin/skills/` |
| Amp | `~/.agents/skills/`, `~/.config/amp/skills/` | `.agents/skills/` |
| Zed | `~/.agents/skills/` | `.agents/skills/` |
| JetBrains Junie | `~/.agents/skills/`, `~/.junie/skills/` | `.agents/skills/` (trusted projects), `.junie/skills/` |
| Vibe CLI | `~/.agents/skills/`, `~/.vibe/skills/` | `.agents/skills/`, `.vibe/skills/` (trusted folders) |
| Antigravity CLI | `~/.gemini/skills/`, `~/.gemini/config/skills/` | `.agents/skills/` |
| Claude Code | `~/.claude/skills/` | `.claude/skills/` |
| Kiro | `~/.kiro/skills/` | `.kiro/skills/` |

Antigravity CLI, Claude Code and Kiro do not read `~/.agents/skills/`. Give them their own copy.

## Check that it works

Start a new conversation and send an audit request with a short sample:

```text
Audit this text for slop patterns:

In today's fast-paced world, communication is more important than ever.
It's not just about sending messages, it's about building real connections.
```

The answer should be a report that begins with `# Slop-Check:` and a verdict line such as
`Verdict: RED (score 6.0; yellow from 2.0, red from 5.0)`. The exact score depends on the catalog
version and on how the assistant judges borderline hits. If the assistant replies with general
advice and no verdict line, the skill did not load. Go back to the guide for your assistant and
check the step that switches the skill on.
