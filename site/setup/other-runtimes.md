---
title: Other skill runtimes
eyebrow: Setup · Agent Skills
lead: Any agent that implements the open Agent Skills format can run slop-check. These guides cover the runtimes whose documentation we checked.
description: Add the slop-check skill folder to Cursor, OpenCode and goose, or to any other runtime that implements the Agent Skills format.
aside: setup
checked: 2026-11-17
verified:
  - title: Agent Skills overview and specification (agentskills.io)
    url: https://agentskills.io/home
  - title: Agent Skills (Cursor Docs)
    url: https://cursor.com/docs/skills
  - title: Skills (OpenCode Docs)
    url: https://opencode.ai/docs/skills
  - title: Agent Skills (goose documentation)
    url: https://goose-docs.ai/docs/guides/context-engineering/using-skills
---

A skill in the [Agent Skills format](https://agentskills.io/home) is a folder with a `SKILL.md` file
that starts with a `name` and a `description`. Agents load the name and description at startup and
read the full instructions when a task matches. The slop-check package follows this layout, so any
compliant runtime can load it from its skills directory.

All runtimes on this page read the shared folder `~/.agents/skills/`. A copy you placed there for
another agent serves them too.

## Cursor

Cursor discovers skills at startup. Agent can use them right away.

| Scope | Folders |
|---|---|
| Project | `.agents/skills/`, `.cursor/skills/` |
| User | `~/.agents/skills/`, `~/.cursor/skills/` |

For compatibility, Cursor also loads the Claude and Codex skill folders, `.claude/skills/` and
`.codex/skills/`, in the project and in your home folder.

1. Download [slop-check.zip]({{ site.download_zip }}).
2. Unzip it into one of the folders above, for example:

   ```sh
   mkdir -p ~/.cursor/skills
   unzip slop-check.zip -d ~/.cursor/skills
   ```

   Keep the folder name `slop-check`. Cursor requires the `name` field to match the folder.
3. Restart Cursor.
4. In Agent chat, type `/` and search for `slop-check` to call the skill directly. Agent also
   applies it on its own when a request matches.

Cloud Agents receive personal skills from `~/.cursor/skills/` only when **Sync Skills for Cloud
Agents** is on under **Settings > Agents**. Automations load only skills from the repository's
`.cursor/skills/` folder.

## OpenCode

OpenCode loads skills on demand through its `skill` tool. A skill without a description stays
hidden from the model.

| Scope | Folders |
|---|---|
| Project | `.opencode/skills/`, `.claude/skills/`, `.agents/skills/` |
| Global | `~/.config/opencode/skills/`, `~/.claude/skills/`, `~/.agents/skills/` |

1. Download [slop-check.zip]({{ site.download_zip }}).
2. Unzip it into one of the folders above, for example:

   ```sh
   mkdir -p ~/.config/opencode/skills
   unzip slop-check.zip -d ~/.config/opencode/skills
   ```

3. Start OpenCode. The model loads the skill when a request matches. Mention `@slop-check` in a
   prompt to load it yourself.

Permission rules in `opencode.json` can restrict skills per agent. If slop-check does not load even
though the folder is in place, look for a rule in that file that denies it.

## goose

Nothing to enable: goose loads skills through its built-in Skills extension, which is on by default.

| Scope | Folder |
|---|---|
| Global | `~/.agents/skills/` |
| Project | `.agents/skills/` |

1. Download [slop-check.zip]({{ site.download_zip }}).
2. Unzip it into `~/.agents/skills/`:

   ```sh
   mkdir -p ~/.agents/skills
   unzip slop-check.zip -d ~/.agents/skills
   ```

3. Run `goose skills list`, or `/skills` inside a session, and look for `slop-check`.
4. goose loads the skill when a request fits its purpose, or when you name it.

## Runtimes not listed here

Look up the skills directory in the runtime's documentation and unzip the package there. Keep the
folder name `slop-check`. If the runtime only accepts a system prompt, use the
[single-file fallback]({{ '/setup/no-skill-support/' | relative_url }}).
