---
title: Microsoft
eyebrow: Setup · Copilot
lead: Install slop-check in GitHub Copilot, in Microsoft 365 Copilot Cowork and in Copilot Studio agents.
description: Add the slop-check skill folder to GitHub Copilot in VS Code, Copilot CLI and the cloud agent, or upload it to Microsoft 365 Copilot Cowork and Copilot Studio.
aside: setup
checked: 2026-11-17
verified:
  - title: Agent skills (GitHub Docs)
    url: https://docs.github.com/en/copilot/concepts/agents/about-agent-skills
  - title: Adding agent skills for GitHub Copilot CLI (GitHub Docs)
    url: https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills
  - title: Use Agent Skills in VS Code (Visual Studio Code Docs)
    url: https://code.visualstudio.com/docs/copilot/customization/agent-skills
  - title: Customize Copilot Cowork (Microsoft Learn)
    url: https://learn.microsoft.com/en-us/copilot/cowork/cowork-customize
  - title: Add and manage an uploaded skill (Microsoft Copilot Studio, Microsoft Learn)
    url: https://learn.microsoft.com/en-us/microsoft-copilot-studio/agents-experience/skills-add-existing
---

GitHub Copilot reads skill folders from disk. Microsoft 365 Copilot Cowork and Copilot Studio take
an uploaded archive with `SKILL.md` at its root, which needs one repacking step.

## GitHub Copilot

Agent skills work in the GitHub Copilot app, in Copilot CLI, in the Copilot cloud agent and code
review on GitHub.com, and in agent mode of VS Code, Visual Studio and JetBrains IDEs. IDE support
depends on the version you use.

| Scope | Folders |
|---|---|
| Project (in the repository) | `.github/skills/`, `.claude/skills/`, `.agents/skills/` |
| Personal (in your home folder) | `~/.copilot/skills/`, `~/.agents/skills/` |

The cloud agent works on the repository, so it needs the project copy.

1. Download [slop-check.zip]({{ site.download_zip }}).
2. For a personal skill, unzip it into `~/.copilot/skills/`:

   ```sh
   mkdir -p ~/.copilot/skills
   unzip slop-check.zip -d ~/.copilot/skills
   ```

   For a project skill, unzip it into `.github/skills/` at the repository root and commit it.
3. In Copilot CLI, start a session or run `/skills reload` in a running one. Then run
   `/skills info slop-check` to confirm that the skill loaded.
4. In VS Code, type `/` in the chat input. `slop-check` appears in the list of skills.
5. Copilot uses the skill when a prompt matches its description. To ask for it directly, name it
   with a leading slash: "Use the /slop-check skill to audit README.md."

## Microsoft 365 Copilot Cowork

Cowork accepts a `.zip` with `SKILL.md` at the archive root. The release zip holds the
`slop-check` folder instead, so repack its contents first.

1. Download [slop-check.zip]({{ site.download_zip }}) and unzip it.
2. Create a new archive from the contents of the `slop-check` folder:

   ```sh
   cd slop-check
   zip -r ../slop-check-cowork.zip .
   ```

   On Windows, in PowerShell, from the folder that contains `slop-check`:

   ```powershell
   Compress-Archive -Path slop-check\* -DestinationPath slop-check-cowork.zip
   ```
3. Open Cowork and select **Plugins** in the left navigation pane.
4. Select **Add**, then **Upload**, and choose `slop-check-cowork.zip`. Cowork validates the file
   and saves the skill to your OneDrive.
5. Start a new conversation to test the skill.

Cowork accepts archives up to 10 MB compressed, 50 MB uncompressed and 100 files. The skill
appears under **Skills** when you filter the Plugins page; from there you can share it with
people in your organization.

## Copilot Studio

Agents built with the Microsoft Copilot harness in Copilot Studio accept uploaded skills.

1. Prepare `slop-check-cowork.zip` as in steps 1 and 2 of the Cowork section.
2. Open your agent in Copilot Studio and select the **Build** tab.
3. In the components panel, select **Skills**.
4. In **Add skill**, select **Upload a skill**.
5. Drop the archive onto the upload box, or select the box and browse to it. Copilot Studio
   validates the file and adds the skill to the agent.

If the skill does not appear after you save, Copilot Studio skipped it at load time. The
troubleshooting table on the linked Microsoft Learn page lists the causes.
