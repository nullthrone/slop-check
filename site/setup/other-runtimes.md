---
title: Other skill runtimes
eyebrow: Setup · Agent Skills
lead: Any agent that implements the open Agent Skills format can run slop-check. This page covers Cursor, OpenCode, goose, Devin Desktop, Amp, Zed, JetBrains Junie and Kiro.
description: Add the slop-check skill folder to Cursor, OpenCode, goose, Devin Desktop, Amp, Zed, JetBrains Junie or Kiro, or to any other runtime that implements the Agent Skills format.
aside: setup
checked: 2026-11-17
verified:
  - title: Agent Skills overview and specification (agentskills.io)
    url: https://agentskills.io/home
  - title: Agent Skills (Cursor Docs)
    url: https://cursor.com/docs/skills
  - title: Run modes (Cursor Docs)
    url: https://cursor.com/docs/agent/security/run-modes
  - title: Skills (OpenCode Docs)
    url: https://opencode.ai/docs/skills
  - title: Using skills (goose documentation)
    url: https://goose-docs.ai/docs/guides/context-engineering/using-skills
  - title: goose permissions (goose documentation)
    url: https://goose-docs.ai/docs/guides/managing-tools/goose-permissions
  - title: Skills (Devin Desktop documentation)
    url: https://docs.devin.ai/desktop/cascade/skills
  - title: Agent Skills (Amp manual)
    url: https://ampcode.com/manual/agent-skills.md
  - title: Skills (Zed documentation)
    url: https://zed.dev/docs/ai/skills
  - title: Agent Skills (JetBrains Junie documentation)
    url: https://junie.jetbrains.com/docs/agent-skills.html
  - title: Skills (Kiro documentation)
    url: https://kiro.dev/docs/skills/
---

A skill in the [Agent Skills format](https://agentskills.io/home) is a folder with a `SKILL.md` file
that starts with a `name` and a `description`. Agents load the name and description at startup and
read the full instructions when a task matches. The slop-check package follows this layout, so any
compliant runtime can load it from its skills directory.

All runtimes on this page take [slop-check.zip]({{ site.download_zip }}) unzipped into one of their
skills folders. Keep the folder name `slop-check`: Cursor, Amp and Kiro require the `name` field to
match the folder.

## Where each runtime looks

| Runtime | Personal folders | Project folders | Call it with |
|---|---|---|---|
| Cursor | `~/.agents/skills/`, `~/.cursor/skills/` | `.agents/skills/`, `.cursor/skills/` | `/slop-check` |
| OpenCode | `~/.agents/skills/`, `~/.config/opencode/skills/`, `~/.claude/skills/` | `.agents/skills/`, `.opencode/skills/`, `.claude/skills/` | `@slop-check` |
| goose | `~/.agents/skills/`, `~/.claude/skills/` | `.agents/skills/`, `.goose/skills/`, `.claude/skills/` | its name, or `/skills slop-check` |
| Devin Desktop | `~/.config/devin/skills/`, `~/.agents/skills/` | `.devin/skills/`, `.agents/skills/`, `.windsurf/skills/` | `/slop-check` |
| Amp | `~/.config/agents/skills/`, `~/.agents/skills/`, `~/.config/amp/skills/`, `~/.claude/skills/` | `.agents/skills/`, `.claude/skills/` | none documented |
| Zed | `~/.agents/skills/` | `.agents/skills/` in the worktree | `/` or an `@` mention |
| JetBrains Junie | `~/.junie/skills/`, `~/.agents/skills/` | `.junie/skills/`, `.agents/skills/` (trusted projects) | `/slop-check` or `$slop-check` |
| Kiro | `~/.kiro/skills/` | `.kiro/skills/` | `/slop-check` |

Every runtime in the table except Kiro reads the shared folder `~/.agents/skills/`. A copy you
placed there for another agent serves them too:

```sh
mkdir -p ~/.agents/skills
unzip slop-check.zip -d ~/.agents/skills
```

All of them also pick the skill on their own when a request matches its description.

## Cursor

Cursor discovers skills when it starts. Besides the folders in the table, it loads skills from the
Claude and Codex skill directories.

1. Download [slop-check.zip]({{ site.download_zip }}).
2. Unzip it into one of the folders in the table, for example:

   ```sh
   mkdir -p ~/.cursor/skills
   unzip slop-check.zip -d ~/.cursor/skills
   ```

3. Restart Cursor.
4. In Agent chat, type `/` and pick `slop-check`, or type `/slop-check` followed by your request.

Cursor preloads the list of skills with their descriptions. When that list is long, Cursor can trim
or drop descriptions, which weakens automatic selection, according to a staff reply on the
[Cursor forum](https://forum.cursor.com/t/skill-descriptions-are-truncated-in-initial-agent-context/163761).
Call the skill with `/slop-check` for reliable use.

The agent runs the scripts a skill references when the skill is invoked. Terminal commands follow
Cursor's run modes, with Auto-review as the default, and the sandbox blocks network access by
default. The slop-check script works offline. Cursor loads files in `references/` on demand.

Cloud Agents receive personal skills from `~/.cursor/skills/` only when **Sync Skills for Cloud
Agents** is on under **Settings** > **Agents** > **Context and Tools**. Automations do not load
synced personal skills. For automations, add the skill to the repository's `.cursor/skills/`
folder.

## OpenCode

OpenCode loads a skill when the model calls its `skill` tool with the skill's ID. A skill without a
description is not advertised to the model.

1. Download [slop-check.zip]({{ site.download_zip }}).
2. Unzip it into one of the folders in the table, for example:

   ```sh
   mkdir -p ~/.config/opencode/skills
   unzip slop-check.zip -d ~/.config/opencode/skills
   ```

3. Start OpenCode. The model loads the skill when a request matches. Mention `@slop-check` in a
   prompt to load it yourself.

OpenCode does not load the contents of supporting files automatically. The model receives up to
ten file paths from the skill folder and has to open the files itself. The slop-check `SKILL.md`
holds the core pattern list and the report layout, so an audit works even if the model opens no
reference file. The skills page does not describe how bundled scripts run.

Permission rules with `action: "skill"` in the OpenCode configuration allow, deny or ask before
each skill, per agent. The documentation's example uses `opencode.jsonc`. If slop-check does not
load although the folder is in place, look for a rule that denies it.

## goose

goose loads skills through its built-in Skills extension, which is on by default.

1. Download [slop-check.zip]({{ site.download_zip }}).
2. Unzip it into `~/.agents/skills/` with the commands above.
3. Run `goose skills list`, or `/skills` inside a session, and look for `slop-check`.
4. goose loads the skill when a request fits its purpose, or when you name it.

goose reads the reference files with the file tools of its Developer extension and runs shell
commands through the same extension. Its default permission mode is Autonomous, in which goose
runs the skill's script without asking you. The goose permissions page describes the other modes,
in case you want to approve commands first.

## Devin Desktop

Devin Desktop was formerly called Windsurf. It reads `.devin/skills/` in the workspace and
`~/.config/devin/skills/` in your home folder, and also reads `.agents/skills/`, the older
`.windsurf/skills/` and `~/.agents/skills/`.

1. Download [slop-check.zip]({{ site.download_zip }}).
2. Unzip it into `~/.config/devin/skills/`:

   ```sh
   mkdir -p ~/.config/devin/skills
   unzip slop-check.zip -d ~/.config/devin/skills
   ```

3. Call the skill with `/slop-check`, or let Devin Desktop pick it when a request matches.

Devin Desktop reads the reference files when the skill is invoked. Its documentation does not
describe script execution.

## Amp

Amp reads skills from a list of folders that starts with `~/.config/agents/skills/` and
`~/.agents/skills/`; the table shows the ones that matter here. Amp can also install skills with
`amp skill add <source>`.

1. Download [slop-check.zip]({{ site.download_zip }}).
2. Unzip it into `~/.config/amp/skills/`, or use the shared folder:

   ```sh
   mkdir -p ~/.config/amp/skills
   unzip slop-check.zip -d ~/.config/amp/skills
   ```

3. Ask for an audit. Amp picks the skill when a request matches its description.

Amp's documentation names no command that calls a skill directly and does not describe script
execution. A skill refers to its files by paths relative to the skill directory.

## Zed

Skills work in the Zed Agent only. Zed reads `~/.agents/skills/` and `.agents/skills/` in the
worktree.

1. Download [slop-check.zip]({{ site.download_zip }}).
2. Unzip it into `~/.agents/skills/` with the commands above.
3. In the Zed Agent, type `/` or use an `@` mention to call the skill. The agent also picks it
   through its `skill` tool when a request matches.

Zed asks you before it runs a skill that you installed yourself. The agent reads reference files on
demand with `read_file` and `list_directory`. Zed's documentation does not describe script
execution.

## JetBrains Junie

Junie reads `.junie/skills/` and `~/.junie/skills/`. It also reads `.agents/skills/` in a trusted
project and `~/.agents/skills/`.

1. Download [slop-check.zip]({{ site.download_zip }}).
2. Unzip it into `~/.junie/skills/`:

   ```sh
   mkdir -p ~/.junie/skills
   unzip slop-check.zip -d ~/.junie/skills
   ```

3. Call the skill with `/slop-check` or `$slop-check`, or let Junie pick it. `/skills` switches
   skills on and off.

Junie executes bundled scripts as needed and reads reference files on demand. Its documentation
does not say whether it asks before it runs a script.

## Kiro

Kiro reads `.kiro/skills/` and `~/.kiro/skills/`. Its documentation does not mention
`.agents/skills/`, so give Kiro its own copy. Kiro can also import a skill from a local folder or a
GitHub URL.

1. Download [slop-check.zip]({{ site.download_zip }}).
2. Unzip it into `~/.kiro/skills/`:

   ```sh
   mkdir -p ~/.kiro/skills
   unzip slop-check.zip -d ~/.kiro/skills
   ```

3. Call the skill with `/slop-check`, or let Kiro pick it when a request matches.

Kiro loads scripts and reference files only as needed, and reads reference files when the
instructions direct it to. Whether it runs the bundled script is not stated.

## Runtimes not listed here

Look up the skills directory in the runtime's documentation and unzip the package there. Keep the
folder name `slop-check`. If the runtime has no skills, use one of the single-file exports described
under [No skill support]({{ '/setup/no-skill-support/' | relative_url }}). For an instruction field
of about 8,000 characters that is `instructions.md`; `system-prompt.md` has about 62,000 characters
and fits API system messages only.
