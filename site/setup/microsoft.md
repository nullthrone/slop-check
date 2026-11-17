---
title: Microsoft
eyebrow: Setup · Copilot
lead: Add slop-check to GitHub Copilot as a skill folder, or upload it to Microsoft 365 Copilot Chat, Copilot Cowork, Agent Builder and Copilot Studio.
description: Add the slop-check skill folder to GitHub Copilot, or upload the flat or lite package to Microsoft 365 Copilot Chat, Copilot Cowork, Agent Builder and Copilot Studio.
aside: setup
checked: 2026-11-17
verified:
  - title: About agent skills (GitHub Docs)
    url: https://docs.github.com/en/copilot/concepts/agents/about-agent-skills
  - title: Adding agent skills for GitHub Copilot CLI (GitHub Docs)
    url: https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills
  - title: Adding skills for Copilot cloud agent (GitHub Docs)
    url: https://docs.github.com/en/copilot/how-tos/use-copilot-agents/cloud-agent/add-skills
  - title: Connected Copilot cloud experience (GitHub Changelog, 2026-10-28)
    url: https://github.blog/changelog/2026-10-28-work-from-anywhere-with-a-new-connected-copilot-cloud-experience/
  - title: Copilot code review agent skills generally available (GitHub Changelog, 2026-07-29)
    url: https://github.blog/changelog/2026-07-29-copilot-code-review-agent-skills-and-mcp-now-generally-available/
  - title: Use Agent Skills in VS Code (Visual Studio Code Docs)
    url: https://code.visualstudio.com/docs/copilot/customization/agent-skills
  - title: Build skills for Microsoft 365 Copilot Chat (Microsoft Learn)
    url: https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/build-copilot-chat-skills
  - title: Create and edit skills in Copilot (Microsoft Support)
    url: https://support.microsoft.com/en-us/microsoft-365-copilot/create-edit-skills-copilot
  - title: Skills in declarative agents (Microsoft Learn)
    url: https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/declarative-agent-skills
  - title: Add skills in Agent Builder (Microsoft Learn)
    url: https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/agent-builder-add-skills
  - title: Customize Copilot Cowork (Microsoft Learn)
    url: https://learn.microsoft.com/en-us/copilot/cowork/cowork-customize
  - title: Use Copilot Cowork (Microsoft Learn)
    url: https://learn.microsoft.com/en-us/copilot/cowork/use-cowork
  - title: Copilot Cowork plugin development (Microsoft Learn)
    url: https://learn.microsoft.com/en-us/copilot/cowork/cowork-plugin-development
  - title: Copilot Cowork FAQ (Microsoft Learn)
    url: https://learn.microsoft.com/en-us/copilot/cowork/cowork-faq
  - title: Add and manage an uploaded skill (Microsoft Copilot Studio, Microsoft Learn)
    url: https://learn.microsoft.com/en-us/microsoft-copilot-studio/agents-experience/skills-add-existing
  - title: Skills overview (Microsoft Copilot Studio, Microsoft Learn)
    url: https://learn.microsoft.com/en-us/microsoft-copilot-studio/agents-experience/skills-overview
  - title: Harnesses overview (Microsoft Copilot Studio, Microsoft Learn)
    url: https://learn.microsoft.com/en-us/microsoft-copilot-studio/harnesses-overview
---

GitHub Copilot reads skill folders from disk. The Microsoft 365 products and Copilot Studio take
an uploaded archive, and each has its own rules for layout and file count. Pick the file from
this table.

| Product | File |
|---|---|
| GitHub Copilot (CLI, VS Code, cloud agent) | [slop-check.zip]({{ site.download_zip }}), unzipped into a skills folder |
| Microsoft 365 Copilot Chat | [slop-check-flat.zip]({{ site.download_flat_zip }}) |
| Agent Builder (declarative agents) | [slop-check-flat.zip]({{ site.download_flat_zip }}) |
| Copilot Studio | [slop-check-flat.zip]({{ site.download_flat_zip }}) |
| Microsoft 365 Copilot Cowork | [slop-check-lite.zip]({{ site.download_lite_zip }}) |

`slop-check-flat.zip` holds the full package with `SKILL.md` at the root of the archive.
`slop-check-lite.zip` has the same layout without the `scripts` folder. Its `SKILL.md` carries the
core pattern list and the report layout, so an audit works from that file alone.

## GitHub Copilot

Agent skills work in the GitHub Copilot app and in Copilot CLI. On GitHub.com the Copilot cloud
agent and Copilot code review use them, and in the editors agent mode does (VS Code, Visual Studio,
JetBrains IDEs). IDE support depends on the version you use.

| Scope | Folders |
|---|---|
| Project (in the repository) | `.github/skills/`, `.claude/skills/`, `.agents/skills/` |
| Personal (in your home folder) | `~/.copilot/skills/`, `~/.agents/skills/` |

The supported folders depend on the surface. In VS Code they also depend on the agent harness you
select. With Copilot, VS Code reads `.github/skills/` and `~/.copilot/skills/`. With Claude it reads
only `.claude/skills/` and `~/.claude/skills/`, and with Codex it reads `.agents/skills/`. The Local
harness, which Microsoft removes in February 2027, also reads the `.claude` and `.agents` folders.
The two Copilot folders work in Copilot CLI as well, so the steps below use them.

1. Download [slop-check.zip]({{ site.download_zip }}).
2. For a personal skill, unzip it into `~/.copilot/skills/`:

   ```sh
   mkdir -p ~/.copilot/skills
   unzip slop-check.zip -d ~/.copilot/skills
   ```

   For a project skill, unzip it into `.github/skills/` at the repository root and commit it.
3. In Copilot CLI, run `/skills reload` in a running session, or start a new one. Then run
   `/skills info slop-check` to confirm that the skill loaded.
4. In VS Code, type `/` in the chat input. `slop-check` appears in the list of skills.
5. Copilot uses the skill when a prompt matches its description. To ask for it directly, name it
   with a leading slash: "Use the /slop-check skill to audit README.md."

Copilot CLI asks for permission before it runs the bundled script through the shell tool, because
slop-check pre-approves no tool in `allowed-tools`. Approve the command to let the script count the
rule-based patterns. If you decline, the skill audits by reading.

### Cloud agent and code review

The Copilot cloud agent reads skills committed to the repository, so commit the project copy in
`.github/skills/`. Cloud sandbox sessions, which are the default, also read personal skills from
`.copilot/skills` in your dotfiles repository. Sessions that run on GitHub Actions do not. Whether
Python is available there to run the script is unverified; without it the skill audits by reading.

Copilot code review reads skills only from `.github/skills/` and uses one when it is relevant to
the review.

## Microsoft 365 Copilot Chat

Skills in Microsoft 365 Copilot Chat are generally available. Copilot Chat takes a zip with
`SKILL.md` at its root and no enclosing folder, which is the layout of the flat package.

1. Download [slop-check-flat.zip]({{ site.download_flat_zip }}).
2. In Copilot Chat, select **Agents**, then **More agents**.
3. Select the drop-down beside **Add**, select **Upload skill** and choose `slop-check-flat.zip`.
4. Keep **Let Copilot use this skill automatically** switched on, so that Copilot picks the skill
   when a request matches its description. You can also select the installed skill explicitly.

Skill scripts run in a sandbox that has no network access and cannot install packages. The
slop-check script needs neither. It needs Python 3.10 or newer, and Microsoft does not state the
sandbox's Python version, so script use here is unverified. If the script cannot run, the skill
audits by reading.

Microsoft recommends keeping `SKILL.md` under 20,000 characters, and the packaged file stays under
that. Skills are not supported in tenants that use Microsoft Purview Information Barriers.

## Agent Builder

Declarative agents built in Agent Builder can carry up to 8 skills. A skill keeps its text out of
the agent instructions, which are limited to 8,000 characters.

1. Download [slop-check-flat.zip]({{ site.download_flat_zip }}).
2. In Agent Builder, open the agent's **Configure** tab, expand **Skills** and select **Add**.
3. Upload the complete `slop-check-flat.zip`.

Agent Builder accepts zips of up to 50 MB with up to 350 files, 25 MB per file and three folder
levels. The flat package fits. Scripts run in a sandbox without network access. The agent picks
the skill from its description; Microsoft documents no way to call a skill by name.

To put slop-check into the agent instructions instead, paste
[instructions.md]({{ site.download_instructions }}), which has at most 7,500 characters. The guide
for [assistants without skills]({{ '/setup/no-skill-support/' | relative_url }}) describes that
route.

## Microsoft 365 Copilot Cowork

Cowork allows at most 20 companion files per skill, counting every file besides `SKILL.md`. The
full package has 22, so Cowork reports a validation error for it. Use the lite package, which
leaves out the scripts. Cowork documents script execution for skills, but slop-check audits fully
without its script.

### Upload the package

1. Download [slop-check-lite.zip]({{ site.download_lite_zip }}).
2. Open Cowork and select **Plugins** in the left navigation pane.
3. Select **Add**, then **Upload**, and choose `slop-check-lite.zip`. Cowork validates the file and
   saves the skill to your OneDrive.
4. Start a new conversation to test the skill.

Microsoft's "Use Copilot Cowork" page describes another path for steps 2 and 3: open the
**Customize** page, select the **Skills** tab, select the arrow next to **Add**, then select
**Upload skill**. The two Microsoft pages disagree; follow the one that matches your Cowork.

The skill appears under **Skills** when you filter the Plugins page. From there you can share it
with specific people in your organization.

### Use a OneDrive folder

Cowork also reads skills from OneDrive. Unzip `slop-check-lite.zip` into
`/Documents/Cowork/skills/slop-check/` in your OneDrive, so that the file
`/Documents/Cowork/skills/slop-check/SKILL.md` exists. Cowork discovers custom skills at the start
of each session. The 20-file limit applies here too, so do not copy the full package.

### Limits and behavior

| Item | Limit |
|---|---|
| Uploaded archive | 10 MB compressed, 50 MB uncompressed, 100 files |
| `SKILL.md` | 1 MB |
| Companion files | 20 per skill, 5 MB each, 10 MB in total |
| Custom skills | 50 |
| `name` | 1 to 64 characters, kebab-case |
| `description` | 1 to 1,024 characters |

Custom skills do not work in Cowork on mobile. Cowork picks a skill by its description and shows
loaded skills as chips in the side panel. Microsoft documents no slash command that calls a skill
in a conversation; in Cowork's custom instructions, `/` references a skill. Microsoft does not
validate custom skills that users create.

## Copilot Studio

Only agents created with the Microsoft Copilot harness accept uploaded skills. In the Customer
Conversation harness the **Add skill** dialog creates generative and topic skills only, and the
standard harness has no skills.

1. Download [slop-check-flat.zip]({{ site.download_flat_zip }}). Microsoft's page says that the zip
   must include a `SKILL.md` file and does not say where. The flat package keeps `SKILL.md` at the
   root, the layout that Microsoft's other skill hosts require. Whether Copilot Studio also accepts
   the folder layout of `slop-check.zip` is unverified.
2. Open your agent in Copilot Studio and select the **Build** tab.
3. In the components panel, select **Skills**.
4. In **Add skill**, select **Upload a skill**.
5. Drop the archive onto the upload box, or select the box and browse to it. Copilot Studio
   validates the file and adds the skill to the agent.

The orchestration runtime activates the skill when a user's message matches its description.
Microsoft documents no way to call a skill by name.

Whether Copilot Studio runs uploaded skill scripts is unverified, since the Microsoft Learn skill
pages do not say so. A
[Microsoft Copilot Studio blog post](https://microsoft.github.io/mcscatblog/posts/copilot-studio-agent-sandbox/)
describes the harness sandbox as a container with a Python runtime, preinstalled libraries and
shell tools, with no outbound network path. Without the script, the skill audits by reading.

If the skill does not appear after you save, Copilot Studio skipped it at load time. The
troubleshooting table on the linked Microsoft Learn page lists the causes, such as a description
that is too long or a `SKILL.md` that is not UTF-8. **Download** returns only `SKILL.md` as a
Markdown file, so keep the zip as your copy of the package.
