---
title: OpenAI
eyebrow: Setup · ChatGPT and Codex
lead: ChatGPT and Codex read skills in the Agent Skills format. Where your ChatGPT plan has no skills, a project with the single-file export does the job.
description: Upload the slop-check skill to ChatGPT, add it to Codex, or use system-prompt.md as project instructions in ChatGPT plans without skills.
aside: setup
checked: 2026-11-17
verified:
  - title: Build skills (ChatGPT Learn, the target of developers.openai.com/codex/skills)
    url: https://learn.chatgpt.com/docs/build-skills
  - title: Skills (OpenAI Academy)
    url: https://academy.openai.com/public/resources/skills
  - title: Skills in ChatGPT (OpenAI Help Center)
    url: https://help.openai.com/en/articles/20001066-skills-in-chatgpt
  - title: Projects in ChatGPT (OpenAI Help Center)
    url: https://help.openai.com/en/articles/10169521-projects-in-chatgpt
---

As of November 2026, OpenAI documents skills in the Agent Skills format for ChatGPT and Codex: a
folder with a `SKILL.md` that holds a `name` and a `description`. Skills do not sync between
ChatGPT and Codex, so install the package in each product you use.

## ChatGPT

Skills in ChatGPT depend on your plan and, in business workspaces, on the workspace settings.
Workspace owners turn skills on and decide who may upload them. OpenAI's help
article lists the plans that currently have skills; if yours has none, use the
[project fallback](#chatgpt-without-skills) below.

1. Download [slop-check.zip]({{ site.download_zip }}).
2. Open **Skills**. In the desktop app it sits in the sidebar.
3. Select **Create**, then **Upload from your computer**, and choose `slop-check.zip`.
4. Wait for the scan to finish. ChatGPT scans uploaded skills before it makes them available.
5. Start a new chat. ChatGPT picks the skill when a request matches its description; type `@` to
   select it explicitly.

Personal skills do not sync between the desktop app and the web or mobile apps. Upload the skill
on each of them if you use both.

## ChatGPT without skills

Projects keep instructions and files for every chat inside them. Project instructions apply only
in that project and take precedence over your global custom instructions.

1. Download [system-prompt.md]({{ site.download_prompt }}).
2. Create a project for the texts you want checked.
3. Open the project's more options menu and select **Project settings**. Paste the content of
   `system-prompt.md` into the instructions.
4. If the instructions field is too short for the whole file, add `system-prompt.md` to the project
   as a file instead and write one line of instructions: "Apply system-prompt.md to every text you
   check or write in this project."
5. Start chats inside the project.

The same approach works for a custom GPT: put the file content into its instructions or attach
the file as knowledge. Check OpenAI's help center for the current menu names.

## Codex

Codex reads skills from the repository and from your home folder. It scans
`.agents/skills` in each folder from the working directory up to the repository root.

1. Download [slop-check.zip]({{ site.download_zip }}).
2. For all repositories, unzip it into `~/.agents/skills/`:

   ```sh
   mkdir -p ~/.agents/skills
   unzip slop-check.zip -d ~/.agents/skills
   ```

   For one repository, unzip it into `.agents/skills/` at the repository root and commit it.
3. Start Codex and run `/skills`, or type `$` to see the available skills. `slop-check` should be
   in the list.
4. Codex selects the skill when a task matches its description. To call it directly, mention
   `$slop-check` in your request.
