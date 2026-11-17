---
title: Mistral
eyebrow: Setup · Le Chat and Vibe
lead: Le Chat's Work tab and the Mistral Vibe command line both follow the Agent Skills standard. Work builds skills from a form; Vibe reads the skill folder.
description: Create the slop-check skill in Le Chat Work from the package files, or add the skill folder to Mistral Vibe.
aside: setup
checked: 2026-11-17
verified:
  - title: Create your first Skill (Mistral Docs, Vibe Work)
    url: https://docs.mistral.ai/getting-started/quickstarts/vibe-work/create-first-skill
  - title: Skills (Mistral Docs, Vibe CLI)
    url: https://docs.mistral.ai/vibe/code/cli/skills
---

## Le Chat Work

Skills live in the Work tab of Le Chat, at [chat.mistral.ai/work](https://chat.mistral.ai/work).
You need a Mistral account with access to Work; workspace admins can force skills on or off.
Mistral's documentation describes creating a skill in a form and attaching supporting files. It
does not describe uploading a finished skill package, so you copy the parts in.

1. Download [slop-check.zip]({{ site.download_zip }}) and unzip it. Open `slop-check/SKILL.md` in a
   text editor.
2. Open Le Chat, switch to the **Work** tab and open **Context > Skills** in the left sidebar.
3. Select **New Skill**.
4. Enter `slop-check` as the title. Copy the `description` line from the top of `SKILL.md` into the
   description field; it tells Work when to activate the skill.
5. Paste the rest of `SKILL.md`, everything below the closing `---` line, into the `SKILL.md` field.
6. Attach the files from the `references` folder as supporting files. If the file limit stops
   you, attach `audit-procedure.md`, `text-patterns.md` and `report-format.md` first; the audit
   needs them.
7. Select **Create Skill**.

If the form does not accept the files, paste the content of
[system-prompt.md]({{ site.download_prompt }}) into the `SKILL.md` field instead. It combines the
skill instructions with the report format and a condensed catalog in one text.

## Mistral Vibe

Vibe exposes each skill as a slash command. It reads project skills only in folders you have
marked as trusted.

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

## Le Chat without Work

For ordinary Le Chat conversations, use the single-file export as described under
[No skill support]({{ '/setup/no-skill-support/' | relative_url }}). Check
[Mistral's documentation](https://docs.mistral.ai/) for the current place to store instructions.
