---
title: Mistral
eyebrow: Setup · Vibe
lead: Le Chat is now Vibe. Vibe Work builds skills from a form, and the Vibe CLI reads the skill folder. Both follow the Agent Skills standard.
description: Create the slop-check skill in Vibe Work (formerly Le Chat) from the lite package files, or add the skill folder to the Vibe CLI.
aside: setup
checked: 2026-11-17
verified:
  - title: Le Chat is now Vibe (Mistral Help Center)
    url: https://help.mistral.ai/en/articles/682992-le-chat-is-now-vibe
  - title: Choose between Chat, Work and Code (Mistral Docs)
    url: https://docs.mistral.ai/vibe/choose-chat-work-code
  - title: Skills (Mistral Docs, Vibe Work)
    url: https://docs.mistral.ai/vibe/work/skills
  - title: Create your first Skill (Mistral Docs, Vibe Work)
    url: https://docs.mistral.ai/getting-started/quickstarts/vibe-work/create-first-skill
  - title: Create a skill (Mistral Docs, Studio)
    url: https://docs.mistral.ai/studio/prompts-and-skills/create-a-skill
  - title: Custom instructions (Mistral Docs)
    url: https://docs.mistral.ai/le-chat/knowledge-integrations/custom-instructions
  - title: Skills (Mistral Docs, Vibe CLI)
    url: https://docs.mistral.ai/vibe/code/cli/skills
  - title: Safety, approvals and permissions (Mistral Docs, Vibe CLI)
    url: https://docs.mistral.ai/vibe/code/safety-approvals-permissions
  - title: Security advisory MAI-2026-003 (Mistral Docs)
    url: https://docs.mistral.ai/resources/security-advisories/MAI-2026-003
---

Le Chat has become Vibe, Mistral's agent for productivity and coding. It has three modes, Vibe
Work, Vibe Code and Vibe Chat, at the same URL and with the same login. Skills live in Vibe Work.
The Vibe CLI, the command-line side of Vibe Code, reads skill folders from disk.

## Vibe Work

Vibe Work runs at [chat.mistral.ai/work](https://chat.mistral.ai/work). You need a Mistral account
with access to Work; workspace admins can force skills on or off. Work creates a skill from a form
with a title, a description, the `SKILL.md` text and optional supporting files. Mistral documents
no import of a finished skill package, so you copy the parts in.

Mistral does not document whether skill scripts run in Work. Work has a Code Interpreter sandbox on
paid plans, but nothing says that it runs a skill's scripts. Do not attach the `scripts` folder.
Take the files from [slop-check-lite.zip]({{ site.download_lite_zip }}), which contains none. Its
`SKILL.md` holds the core pattern list and the report layout, so the audit works without scripts.

1. Download [slop-check-lite.zip]({{ site.download_lite_zip }}) and unzip it into a new folder. You
   get `SKILL.md` and a `references` folder. Open `SKILL.md` in a text editor.
2. Open [chat.mistral.ai/work](https://chat.mistral.ai/work) and select **Context**, then
   **Skills**, in the left sidebar.
3. Select **New Skill**.
4. Enter `slop-check` as the title. Copy the `description` line from the top of `SKILL.md` into the
   description field; it tells Work when to activate the skill.
5. Paste the rest of `SKILL.md`, everything below the closing `---` line, into the `SKILL.md`
   field. Whether the field expects the frontmatter block as well is not documented.
6. Add the files of the `references` folder as supporting files. Work limits the number of
   supporting files and does not publish the number. If the limit stops you, add
   `text-patterns.md`, `report-format.md` and `audit-procedure.md` first.
7. Select **Create Skill**.

If the form accepts text only, paste [instructions.md]({{ site.download_instructions }}) into the
`SKILL.md` field instead. It holds the audit procedure, the report layout and the scored patterns
in at most 7,500 characters.

Work offers two other ways to create a skill. In a conversation, ask Work to "save this as a
Skill". In Mistral Studio, create the skill under **Skills** with **New Skill**, then select
**Publish to Vibe** to make it available in Work.

### Call the skill

Work activates the skill when a request matches its description. To call it yourself, type `/`
and pick the skill, type `/slop-check`, or name the skill in your prompt. Mistral's getting-started
page shows `@` for the same purpose. Whether Work derives the command name from the title is not
documented; if `/slop-check` does not match, use the `/` picker.

## Vibe Chat and custom instructions

Mistral is merging the Chat tab into Work, for self-serve plans first and for Enterprise within
six months. Legacy agents map to skills. Custom instructions, under **Context** > **Instructions**,
are meant to be short: Mistral advises "a few well-written sentences", and the instructions of an
active skill override them. They have no room for slop-check. Create the Work skill instead.

## Vibe CLI

Use Vibe 2.25.4 or later. Mistral's security advisory MAI-2026-003 describes six ways to bypass
shell permissions in earlier versions, fixed in 2.25.4.

Vibe exposes each skill as a slash command and also picks a skill when a request matches its
description. It reads project skills only in folders you have marked as trusted.

1. Download [slop-check.zip]({{ site.download_zip }}).
2. For all projects, unzip it into your user skills folder:

   ```sh
   mkdir -p ~/.vibe/skills
   unzip slop-check.zip -d ~/.vibe/skills
   ```

   `~/.agents/skills/` works too. For one project, use `.vibe/skills/` or `.agents/skills/` in the
   project folder.
3. Start Vibe and call the skill with `/slop-check`, followed by your request, for example
   `/slop-check audit README.md`.

The skill runs its script through Vibe's Bash tool. The default agent, `accept-edits`, still asks
before it runs a shell command; read-only commands such as `ls` and `cat` run without asking.
Approve the command to let the script count the rule-based patterns, or decline it and the skill
audits by reading. Vibe reads a skill's `allowed-tools` field without enforcing it, and slop-check
sets none. With `auto-approve` (`--yolo`), Vibe approves every command without asking.
