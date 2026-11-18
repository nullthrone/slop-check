---
title: Anthropic
eyebrow: Setup · Claude
lead: Upload slop-check once to claude.ai for the Claude apps and Claude Code, install it as a skill folder, or use it through the Claude API and the Claude Agent SDK.
description: Upload the slop-check skill to claude.ai for the Claude apps, Cowork, the Office add-ins and Claude Code, add it to Claude Code as a skill folder, or use it through the Claude API and the Claude Agent SDK.
aside: setup
checked: 2026-11-18
verified:
  - title: Use skills in Claude (Claude Help Center)
    url: https://support.claude.com/en/articles/12512180-use-skills-in-claude
  - title: How to create custom skills (Claude Help Center)
    url: https://support.claude.com/en/articles/12512198-how-to-create-custom-skills
  - title: Create custom skills (Claude.ai Documentation)
    url: https://claude.com/docs/skills/how-to
  - title: Create and edit files with Claude (Claude Help Center)
    url: https://support.claude.com/en/articles/12111783-create-and-edit-files-with-claude
  - title: Use Claude Cowork on web, desktop, and mobile (Claude Help Center)
    url: https://support.claude.com/en/articles/15520349-use-claude-cowork-on-web-desktop-and-mobile
  - title: Agent Skills overview (Claude Platform Docs)
    url: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview
  - title: Using Agent Skills with the API (Claude Platform Docs)
    url: https://platform.claude.com/docs/en/build-with-claude/skills-guide
  - title: Code execution tool (Claude Platform Docs)
    url: https://platform.claude.com/docs/en/agents-and-tools/tool-use/code-execution-tool
  - title: Extend Claude with skills (Claude Code Docs)
    url: https://code.claude.com/docs/en/skills
  - title: Settings (Claude Code Docs)
    url: https://code.claude.com/docs/en/settings
  - title: Extend agents with skills (Claude Agent SDK Docs)
    url: https://code.claude.com/docs/en/agent-sdk/skills
---

Claude reads skills in the Agent Skills format, which is the format of the package. A skill you
upload to claude.ai belongs to your Claude account. It works in claude.ai, in Claude Desktop, in
Cowork on the web, desktop and mobile, in the Claude add-ins for Excel, PowerPoint, Word and
Outlook, and in Claude Code when you sign in with the same account. The Claude API keeps its own
skills, so upload the skill there separately.

Use [slop-check.zip]({{ site.download_zip }}) for every product on this page.

## Claude apps (web, desktop, mobile)

Skills need code execution. The Help Center lists skills for the Free, Pro, Max, Ultra, Team and
Enterprise plans. Anthropic's platform documentation lists custom skills only from Pro upward, so
uploading on the Free plan is unverified.

1. Download [slop-check.zip]({{ site.download_zip }}) and keep it zipped. The archive holds the
   folder `slop-check`, which is the layout claude.ai expects. claude.ai does not recognize a
   `SKILL.md` at the root of a zip, so `slop-check-flat.zip` and `slop-check-lite.zip` do not
   work here.
2. On a Free, Pro, Max or Ultra plan, open **Settings > Capabilities** and turn on **Code execution
   and file creation**. The updated settings layout calls it **Create and edit files**. On Team
   and Enterprise plans, the organization settings below apply.
3. Open **Customize > Skills**.
4. Select **+**, then **+ Create skill**, then **Upload a skill**.
5. Choose `slop-check.zip`. The skill appears in your list.
6. Make sure the toggle next to slop-check is on.
7. Start a new chat and run the check from the [setup overview]({{ '/setup/' | relative_url }}#check-that-it-works).

Upload the skill in a browser. Claude Desktop has the same **Customize > Skills** page, and users
report the same upload dialog there. The Help Center gives no upload steps for the mobile apps.
Cowork on mobile lists skills among its features, so the uploaded skill is available there.
Whether ordinary chat in the mobile apps uses it is not documented.

Team plans have code execution and skills switched on by default. On Enterprise plans, an owner
must check that both **Code execution and file creation** and **Skills** are on under
**Organization settings > Plugins & skills**, on the **Policy** tab. In one place the Help Center
calls the first switch **Cloud code execution and file creation**. Organizations with HIPAA
readiness or other regulated configurations have skills off by default. Owners can also upload
the skill once for the whole organization. Where an Enterprise organization has skill scanning
turned on, each upload is checked before it can run, which usually takes one to two minutes.

### What works here

| Feature | Behavior |
|---|---|
| Automatic use | Claude uses the skill when a request matches its description. |
| Explicit call | Name it in the request, for example "Use the slop-check skill to audit this text." In the Office add-ins, type `/` in the sidebar and select it. Whether `/` lists an uploaded skill in chat is unverified. |
| Bundled scripts | They run in Claude's code execution container. Anthropic does not document the Python version there. Network access depends on the plan and on admin settings; the checker needs none. |
| Reference files | Claude opens `SKILL.md` and then the files it names, as it needs them. |

### Upload rules

The Help Center allows a skill name of up to 64 characters and a description of up to 200.
Anthropic's newer guide on claude.com gives 1,024 characters for the description, the limit of the
Agent Skills specification. Until the two agree, treat 200 as the safe limit. The slop-check
description has 196. The frontmatter may hold only `name`, `description`, `license`,
`compatibility`, `metadata` and `allowed-tools`; any other key makes the upload fail. Users report
that the upload dialog rejects archives with more than 200 files, and the package stays far below
that.

## Claude Code

Claude Code can load slop-check from your claude.ai account or from a skill folder on disk. Use one
of the two on each computer.

### Use your claude.ai upload

From version 2.1.273, Claude Code loads the skills enabled for your claude.ai account when you
sign in with that account (`/login`). It downloads them into `~/.claude/skills/synced/` when a
session starts and checks for changes about every 10 minutes while you work.

1. Upload the skill to claude.ai as described above.
2. Start Claude Code signed in with the same Claude account.
3. Run `/skills`. slop-check is listed under **claude.ai sync**.

The sync is one-way: it reads from your Claude account and never changes it. It does not run when
Claude Code signs in with an API key or runs on a cloud provider such as Amazon Bedrock. Cowork
and Claude Code on the web load your account's skills as well, and neither reads
`~/.claude/skills/` on your computer. Users report that the Code tab of Claude Desktop under WSL
does not load account skills; install the skill folder there instead.

Do not install a second copy in `~/.claude/skills/` while the sync is on. With two copies,
`/slop-check` runs the local one, the synced one answers only to `/anthropic-skills:slop-check`,
and both descriptions sit in the skill list. To use a local copy on a computer, turn the sync off
there in your user settings, `~/.claude/settings.json`:

```json
{
  "syncClaudeAiSkills": false
}
```

### Install a skill folder

A personal skill works in all your projects on this computer. A project skill lives in the
repository and reaches everyone who clones it.

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
4. Start Claude Code. A running session picks up the new skill by itself. If the skills folder
   did not exist when the session started, run `/reload-skills`.

### What works here

| Feature | Behavior |
|---|---|
| Automatic use | Claude Code uses the skill when a request matches its description. |
| Explicit call | `/slop-check`. A synced copy answers to `/anthropic-skills:slop-check` while another skill uses the short name. |
| Bundled scripts | They run through the Bash tool with the Python of the computer or cloud environment. The checker needs Python 3.10 or newer and no network. Claude Code asks before it runs a command unless you have allowed it. |
| Reference files | Claude Code reads them as it needs them. |

## Claude API

A claude.ai upload does not reach the API. Upload the skill through the Skills API, which needs
no beta header. Custom skills are shared with everyone in your API workspace.

1. Download [slop-check.zip]({{ site.download_zip }}). The API takes the zip as it is: `SKILL.md`
   may sit at the upload root or at the top of one enclosing folder. Uploads must stay under
   30 MB uncompressed, and the description under 1,024 characters.
2. Upload it with `POST /v1/skills`. The response contains the skill ID.
3. In each Messages API request, list the skill in `container.skills` with the type `custom` and
   include the code execution tool. One request takes up to 20 skills.

With the Python SDK:

```python
import anthropic

client = anthropic.Anthropic()
skill = client.skills.create(files=[open("slop-check.zip", "rb")])

response = client.messages.create(
    model="claude-opus-5-5",
    max_tokens=4096,
    container={"skills": [{"type": "custom", "skill_id": skill.id, "version": "latest"}]},
    messages=[{"role": "user", "content": "Use the slop-check skill to audit this text: ..."}],
    tools=[{"type": "code_execution_20250825", "name": "code_execution"}],
)
```

Use a model that supports the code execution tool. The request format, the version handling and
the other SDKs are described in
[Using Agent Skills with the API](https://platform.claude.com/docs/en/build-with-claude/skills-guide).

### What works here

| Feature | Behavior |
|---|---|
| Automatic use | Claude uses the skill when the request matches its description. |
| Explicit call | Ask for it in the message, for example "Use the slop-check skill to audit this text." The API documents no slash command. |
| Bundled scripts | They run in the code execution container: Python 3.11, no internet access and no package installs at runtime. The checker needs neither. |
| Reference files | Claude reads them through the code execution tool as it needs them. |

## Claude Agent SDK

The Agent SDK loads skills from the file system. It has no API for registering skills in code,
and the claude.ai sync does not apply to sessions that authenticate with an API key.

1. Unzip the package into `.claude/skills/` of the project the agent works in (or of a parent
   folder up to the repository root), or into `~/.claude/skills/`.
2. Keep the `user` and `project` setting sources. The default options load both; if you set
   `setting_sources` (Python) or `settingSources` (TypeScript) yourself, include them.
3. Allow the skill, and allow `Read` and `Bash` so the agent can open the reference files and run
   the checker:

   ```python
   options = ClaudeAgentOptions(
       setting_sources=["user", "project"],
       skills=["slop-check"],
       allowed_tools=["Read", "Bash"],
   )
   ```

4. Check the `skills` array of the `init` system message at the start of the stream. It lists
   `slop-check` once the skill has loaded.

### What works here

| Feature | Behavior |
|---|---|
| Automatic use | Claude uses the skill when a prompt matches its description. |
| Explicit call | Send `/slop-check` in the prompt. |
| Bundled scripts | They run when the session allows `Bash`, with the Python of the machine the agent runs on (3.10 or newer). Without `Bash`, the agent does the audit by hand. |
| Reference files | Read when the session allows `Read` or `Bash`. |

## Troubleshooting claude.ai

### Skills are greyed out or the Skills page is missing

Code execution is off, either for you or for the organization. On Free, Pro, Max and Ultra, turn
it on under **Settings > Capabilities**. On Team and Enterprise, ask the organization owner.

### The option to create or upload a skill is missing

On Team and Enterprise plans, the owner may have turned off **User-created skills**. On
Enterprise plans with custom roles, your role may lack the **Create skills** capability. Skills
the owner provisions still work.

### Claude does not use the skill

Check that the toggle next to slop-check is on in **Customize > Skills**. Then name the skill in
the request: "Use the slop-check skill to audit this text."

### The upload fails

The Help Center lists these causes: the archive exceeds the size limit, the folder name does not
match the skill name, `SKILL.md` is missing, or the name or description contains invalid characters.
A `SKILL.md` at the root of the zip, without the enclosing `slop-check` folder, is not recognized
either; that is the layout of `slop-check-flat.zip` and `slop-check-lite.zip`. A frontmatter key
outside the six allowed ones also makes it fail, and users report the same for archives with more
than 200 files. The release zip meets all of these rules. If the upload of an unmodified
`slop-check.zip` fails, compare the message with [How to create custom
skills](https://support.claude.com/en/articles/12512198-how-to-create-custom-skills) and [open an
issue]({{ site.repository_url }}/issues).
