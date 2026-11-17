---
title: Anthropic
eyebrow: Setup · Claude
lead: Install slop-check in the Claude apps, in Claude Code, through the Claude API and in the Claude Agent SDK.
description: Upload the slop-check skill to claude.ai, add it to Claude Code as a personal or project skill, or use it through the Claude API and the Claude Agent SDK.
aside: setup
checked: 2026-11-17
verified:
  - title: Use skills in Claude (Claude Help Center)
    url: https://support.claude.com/en/articles/12512180-use-skills-in-claude
  - title: How to create custom skills (Claude Help Center)
    url: https://support.claude.com/en/articles/12512198-creating-custom-skills
  - title: Agent Skills overview (Claude Platform Docs)
    url: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview
  - title: Using Agent Skills with the API (Claude Platform Docs)
    url: https://platform.claude.com/docs/en/build-with-claude/skills-guide
  - title: Extend Claude with skills (Claude Code Docs)
    url: https://code.claude.com/docs/en/skills
  - title: Extend agents with skills (Claude Agent SDK Docs)
    url: https://code.claude.com/docs/en/agent-sdk/skills
---

Claude reads skills in the Agent Skills format, so the package works without changes. Custom
skills do not sync between surfaces: a skill uploaded to claude.ai is not available in Claude
Code or through the API. Install it once for each surface you use.

## Claude apps (web, desktop, mobile)

Skills need code execution. The Help Center lists skills for the Free, Pro, Max, Ultra, Team and
Enterprise plans.

1. Download [slop-check.zip]({{ site.download_zip }}) and keep it zipped. Claude expects the
   archive to contain the skill folder, which is how the package is built.
2. Open **Settings > Capabilities** and turn on **Code execution and file creation**. Newer
   layouts call the switch **Create and edit files**.
3. Open **Customize > Skills**.
4. Select **+**, then **+ Create skill**, then **Upload a skill**.
5. Choose `slop-check.zip`. The skill appears in your list.
6. Make sure the toggle next to slop-check is on.
7. Start a new chat and run the check from the [setup overview]({{ '/setup/' | relative_url }}#check-that-it-works).

The Help Center gives one set of steps for all Claude apps and no separate steps for the mobile
apps. Upload the skill in a browser or in the desktop app.

On Team plans, code execution and skills are on by default. On Enterprise plans, an owner turns
them on under **Organization settings > Plugins & skills**, on the **Policy** tab. If the create or
upload option is missing, the owner may have turned off **User-created skills**. Owners can also
upload the skill once for the whole organization.

## Claude Code

Claude Code reads skills from the file system. A personal skill works in all your projects; a
project skill lives in the repository and reaches everyone who clones it.

1. Download [slop-check.zip]({{ site.download_zip }}).
2. For a personal skill, unzip it into `~/.claude/skills/`:

   ```sh
   mkdir -p ~/.claude/skills
   unzip slop-check.zip -d ~/.claude/skills
   ```

   For a project skill, unzip it into `.claude/skills/` at the repository root and commit the
   folder:

   ```sh
   mkdir -p .claude/skills
   unzip slop-check.zip -d .claude/skills
   ```

3. Check that the file `~/.claude/skills/slop-check/SKILL.md` (or
   `.claude/skills/slop-check/SKILL.md`) exists.
4. Start Claude Code. It uses the skill when a request matches the skill's description, and you
   can call it directly with `/slop-check`.

## Claude API

The API runs skills inside the container of the code execution tool. Skills there have no network
access, which slop-check does not need.

1. Unzip [slop-check.zip]({{ site.download_zip }}).
2. Upload the files of the `slop-check` folder through the Skills API (`/v1/skills`). The response
   contains the skill ID. Custom skills uploaded this way are shared with the whole workspace.
3. In each Messages API request, list the skill ID in the `container` parameter and include the
   code execution tool.

The request format, headers and size limits are in
[Using Agent Skills with the API](https://platform.claude.com/docs/en/build-with-claude/skills-guide).

## Claude Agent SDK

The Agent SDK loads skills from the same directories as Claude Code. It has no API for registering
skills in code.

1. Unzip the package into `.claude/skills/` of the project the agent works in, or into
   `~/.claude/skills/`.
2. Keep the `user` and `project` setting sources. The default options load both; if you set
   `setting_sources` (Python) or `settingSources` (TypeScript) yourself, include them.
3. To limit the agent to this skill, pass its name in the `skills` option:

   ```python
   options = ClaudeAgentOptions(
       setting_sources=["user", "project"],
       skills=["slop-check"],
   )
   ```

4. Check the `skills` array of the `init` system message at the start of the stream. It lists
   `slop-check` once the skill has loaded.

## If the upload fails

The Help Center lists the packaging rules for uploads: the archive must contain the skill folder,
the folder name must match the skill name, and the name and description must stay within the
documented lengths. Compare the error message with
[How to create custom skills](https://support.claude.com/en/articles/12512198-creating-custom-skills)
and [open an issue]({{ site.repository_url }}/issues) if the package breaks one of the rules.
