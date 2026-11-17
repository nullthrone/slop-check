---
title: OpenAI
eyebrow: Setup · ChatGPT and Codex
lead: Upload slop-check to ChatGPT where your plan has skills, add the folder to Codex, or attach it through the OpenAI API. Without skills, a ChatGPT project with instructions.md takes its place.
description: Upload the slop-check skill to ChatGPT, add it to Codex, attach it to the shell tool of the OpenAI API, or set up a ChatGPT project with instructions.md and knowledge.md.
aside: setup
checked: 2026-11-17
verified:
  - title: Build skills (ChatGPT Learn, the target of developers.openai.com/codex/skills)
    url: https://learn.chatgpt.com/docs/build-skills
  - title: Skills and plugins (ChatGPT Learn)
    url: https://learn.chatgpt.com/docs/skills-and-plugins
  - title: Projects (ChatGPT Learn)
    url: https://learn.chatgpt.com/docs/projects
  - title: Sandboxing (ChatGPT Learn)
    url: https://learn.chatgpt.com/docs/sandboxing
  - title: Agent approvals and security (ChatGPT Learn)
    url: https://learn.chatgpt.com/docs/agent-approvals-security
  - title: Cloud environments (ChatGPT Learn)
    url: https://learn.chatgpt.com/docs/environments/cloud-environments
  - title: Skills (OpenAI Academy)
    url: https://academy.openai.com/public/resources/skills
  - title: ChatGPT pricing
    url: https://chatgpt.com/pricing/
  - title: Skills (OpenAI API documentation)
    url: https://developers.openai.com/api/docs/guides/tools-skills
  - title: Shell (OpenAI API documentation)
    url: https://developers.openai.com/api/docs/guides/tools-shell
  - title: Skills in ChatGPT (OpenAI Help Center, read through search excerpts)
    url: https://help.openai.com/en/articles/20001066-skills-in-chatgpt
  - title: Projects in ChatGPT (OpenAI Help Center, read through search excerpts)
    url: https://help.openai.com/en/articles/10169521-projects-in-chatgpt
  - title: File uploads FAQ (OpenAI Help Center, read through search excerpts)
    url: https://help.openai.com/en/articles/8555545-file-uploads-faq
  - title: Custom GPT retirement and migration FAQ (OpenAI Help Center, read through search excerpts)
    url: https://help.openai.com/en/articles/20001519-custom-gpt-retirement-and-migration-faq
---

ChatGPT and Codex read skills in the Agent Skills format: a folder with a `SKILL.md` that holds a
`name` and a `description`. Skills do not sync between ChatGPT on the web and Codex. The ChatGPT
desktop app also keeps its personal skills apart from the web and mobile apps, so install the
package in each place you use.

## ChatGPT

OpenAI's Help Center describes personal skills as generally available on Business, Enterprise,
Healthcare and Edu. The pricing page also lists skills on Free, Go, Plus and Pro; whether those
plans can upload their own skills is unverified. In Enterprise and Edu workspaces skills are off by
default, and the admin permission **Enable skill uploading** controls uploads. If your plan has no
skills, use the [project fallback](#chatgpt-without-skills) below.

1. Download [slop-check.zip]({{ site.download_zip }}). OpenAI does not document the upload format
   for ChatGPT. A zip with one top-level folder, the layout of this archive, has worked in user
   reports.
2. On [chatgpt.com](https://chatgpt.com), select **Plugins** in the sidebar, then the **Skills**
   tab.
3. Select **Create**, then **Upload from your computer**, and choose `slop-check.zip`.
4. Wait for the scan. ChatGPT scans uploaded skills first; most are available right after it, some
   get the status **Needs Review** or **Blocked**.
5. Start a new chat and run the check from the
   [setup overview]({{ '/setup/' | relative_url }}#check-that-it-works).

Users report that skills uploaded on the web also appear in the mobile apps. The desktop app is
different: **Skills** sits in its sidebar, but its personal skills do not sync with the web and
mobile apps, and OpenAI does not document an upload there. Users report that it reads local skill
folders; that it reads `~/.agents/skills/`, the Codex folder described [below](#codex), is likely
but unverified.

If the skill is listed but ChatGPT says it is not available in this session, wait about 20
minutes; if it stays unavailable, OpenAI support's workaround is to upload the skill again under a
new name. One user found uploaded skills unavailable in Chat but working in ChatGPT Work.

### What works here

| Feature | Behavior |
|---|---|
| Automatic use | ChatGPT uses the skill when a request matches its description. |
| Explicit call | Type `@` and select slop-check. |
| Bundled scripts | OpenAI does not document whether ChatGPT runs a skill's bundled scripts, or with which Python. ChatGPT Work can run code in an isolated environment, but no source confirms that it runs these scripts. The skill works without them. |
| Reference files | ChatGPT loads `SKILL.md` when it uses the skill. How it opens the reference files is not documented; `SKILL.md` alone carries the core pattern list and the report layout. |

## ChatGPT without skills

A project keeps instructions and files for every chat inside it. Project instructions apply only
in that project and take precedence over your global custom instructions. OpenAI publishes no
length limit for them; users report about 8,000 characters. `instructions.md` holds the audit
procedure, the report layout, the thresholds and the scored patterns in at most 7,500 characters.

1. Download [instructions.md]({{ site.download_instructions }}) and
   [knowledge.md]({{ site.download_knowledge }}).
2. Create a project for the texts you want checked.
3. Open the project's more options menu (**•••**) and select **Project settings**. Paste the
   content of `instructions.md` into the instructions.
4. Add `knowledge.md` to the project's **Sources** as a file. It holds the full catalog with
   examples and the detailed procedures. ChatGPT finds project files by search and does not
   necessarily read them in full, so the rules that must always apply stay in the instructions.
5. Start chats inside the project and run the check from the
   [setup overview]({{ '/setup/' | relative_url }}#check-that-it-works).

A project holds up to 5 files on Free, 25 on Go and Plus, and 40 on Pro, Business, Enterprise and
Edu. `knowledge.md` uses one of them.

Global custom instructions take 5,000 characters, or 1,500 on Free and Go, so `instructions.md`
does not fit there. Use a project or a skill. The single-file `system-prompt.md` (about 62,000
characters) fits no ChatGPT instruction field; it is meant for API system messages, as described
under [No skill support]({{ '/setup/no-skill-support/' | relative_url }}). OpenAI retires custom
GPTs on 2026-12-11, so this guide does not cover them.

### What works here

| Feature | Behavior |
|---|---|
| Automatic use | The instructions apply to every chat in the project. |
| Explicit call | Not needed. Start the chat inside the project. |
| Bundled scripts | None. The exports contain no scripts. |
| Reference files | `knowledge.md` is found by search and not necessarily read in full. |

## Codex

Codex reads skills from the repository and from your home folder. It scans `.agents/skills` in
each folder from the working directory up to the repository root, then `~/.agents/skills`.

1. Download [slop-check.zip]({{ site.download_zip }}).
2. For all repositories, unzip it into `~/.agents/skills/`:

   ```sh
   mkdir -p ~/.agents/skills
   unzip slop-check.zip -d ~/.agents/skills
   ```

   For one repository, unzip it into `.agents/skills/` at the repository root and commit it.
3. Start Codex and run `/skills`, or type `$` to see the available skills. `slop-check` should be
   in the list. Codex detects new skills by itself; if the skill does not appear, restart Codex.

Codex Cloud sees only skills committed to the repository. Personal skills from your computer are
not synced to cloud environments.

### What works here

| Feature | Behavior |
|---|---|
| Automatic use | Codex uses the skill when a task matches its description. |
| Explicit call | Mention `$slop-check` in the request. `/skills` lists the installed skills. |
| Bundled scripts | Codex runs them when needed, in its sandbox, with your Python (3.10 or newer). The default sandbox keeps network access off, which the checker does not need. In Codex Cloud they run in the cloud container. |
| Reference files | Codex reads them when it needs them. |

## OpenAI API

The Responses API runs skills with the shell tool. Upload the skill once, then attach it to a
hosted container.

1. Download [slop-check.zip]({{ site.download_zip }}). The API takes a `.zip` that contains a
   single top-level folder, which is the layout of this archive. A skill may hold up to 500 files
   and exactly one `SKILL.md`; the zip may be up to 50 MB.
2. Upload it to `/v1/skills`. The response contains the skill ID:

   ```sh
   curl -X POST 'https://api.openai.com/v1/skills' \
     -H "Authorization: Bearer $OPENAI_API_KEY" \
     -F 'files=@./slop-check.zip;type=application/zip'
   ```

3. In each Responses API request, attach the skill to the shell tool:

   ```json
   "tools": [
     {
       "type": "shell",
       "environment": {
         "type": "container_auto",
         "skills": [{ "type": "skill_reference", "skill_id": "<skill_id>" }]
       }
     }
   ]
   ```

A version request can return `404` for a moment right after the upload; retry briefly. The local
shell mode takes skill files from local paths instead of a skill reference. Without skills, send
`system-prompt.md` as the system message, as described under
[No skill support]({{ '/setup/no-skill-support/' | relative_url }}).

### What works here

| Feature | Behavior |
|---|---|
| Automatic use | The model sees the skill's name and description and decides when to use it. |
| Explicit call | Tell the model to "use the slop-check skill" in the input. |
| Bundled scripts | They run in the hosted container, which has Python 3.11 and no outbound network access by default. The checker needs none. |
| Reference files | The model reads them through the shell as it needs them. |
