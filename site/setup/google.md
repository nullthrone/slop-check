---
title: Google
eyebrow: Setup · Gemini
lead: Upload the script-free slop-check-lite to the Gemini app, the full package to Gemini Enterprise, or add the skill folder to Gemini CLI and Antigravity.
description: Upload slop-check-lite.zip to the Gemini app, deactivate a converted slop Gem, upload slop-check.zip to Gemini Enterprise, and add the skill folder to Gemini CLI or Antigravity.
aside: setup
checked: 2026-11-18
verified:
  - title: Create and manage skills for Gemini Apps (Gemini Apps Help)
    url: https://support.google.com/gemini/answer/17094296?hl=en
  - title: Create and manage skills for Gemini Apps, Android version (Gemini Apps Help)
    url: https://support.google.com/gemini/answer/17094296?hl=en&co=GENIE.Platform%3DAndroid
  - title: Write effective skills for Gemini Apps (Gemini Apps Help)
    url: https://support.google.com/gemini/answer/17102773?hl=en
  - title: About the transition from Gems to skills (Gemini Apps Help)
    url: https://support.google.com/gemini/answer/18560919?hl=en
  - title: Manage your tasks and workflows in Gemini Apps (Gemini Apps Help)
    url: https://support.google.com/gemini/answer/17094507?hl=en
  - title: About the transition from Gems to skills (Google Workspace)
    url: https://knowledge.workspace.google.com/p/gems-migration
  - title: Prepare your organization for the transition to skills (Google Workspace Admin)
    url: https://knowledge.workspace.google.com/admin/generative-ai/gemini-app/prepare-for-the-transition-to-skills
  - title: Learn how skills work in Google Workspace and Workspace Studio (Workspace Studio Help)
    url: https://support.google.com/workspace-studio/answer/17307546?hl=en
  - title: Create and manage skills (Gemini Enterprise)
    url: https://docs.cloud.google.com/gemini/enterprise/docs/skills
  - title: Manage skills (Gemini Enterprise)
    url: https://docs.cloud.google.com/gemini/enterprise/docs/manage-skills
  - title: Agent Skills (Gemini CLI documentation)
    url: https://geminicli.com/docs/cli/skills/
  - title: Creating Agent Skills (Gemini CLI documentation)
    url: https://geminicli.com/docs/cli/creating-skills/
  - title: CLI reference, skills management (Gemini CLI documentation)
    url: https://geminicli.com/docs/cli/cli-reference/
  - title: Agent skills (Antigravity documentation)
    url: https://antigravity.google/docs/skills/
  - title: Transitioning Gemini CLI to Antigravity CLI (Google Developers Blog)
    url: https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/
  - title: Moving from Gemini CLI to Antigravity CLI (Antigravity documentation)
    url: https://antigravity.google/docs/cli/gcli-migration
---

The Gemini app, Gemini Enterprise and Google Workspace keep separate skill libraries, so a skill
created in the Gemini app is not available in the other two. Install slop-check in each. The
Gemini app takes the script-free [slop-check-lite.zip]({{ site.download_lite_zip }}), while Gemini
Enterprise, Gemini CLI and Antigravity take the full [slop-check.zip]({{ site.download_zip }}).

## Gems and skills

Google is replacing Gems with skills. Since 2026-11-17, Gems in personal accounts are read-only;
Google removes them on 2026-12-17 and recreates each one as a skill. Work and school accounts
follow in 2027.

A slop-check Gem you built earlier comes back as a second slop-check skill. Keep it inactive and
install the package as described below. To deactivate the converted copy, open it on the Skills
page and select **More**, then **Deactivate**.

## Gemini app

The help page asks only that you are 18 or older and signed in. You can upload skills only on
[gemini.google.com](https://gemini.google.com) and in the Gemini app on Mac. The Android and iOS
apps can use an uploaded skill but cannot upload one.

Do not count on the bundled scripts in Gemini chat. Google's help page lists `.py` and `.sh` among
the supported upload types and says that scripts that require access to the internet are not
supported, but it does not say that chat runs scripts. In tests Gemini answered that the scripts
cannot run in its environment. The skill is built to work without them: its `SKILL.md` contains the
core pattern list and the report layout, so an audit works from `SKILL.md` alone. The lite package
holds `SKILL.md` and the `references` folder and leaves the scripts out. Use it here; in reported
tests, Gemini either refused the full package because of its scripts or stopped at them.

1. Download [slop-check-lite.zip]({{ site.download_lite_zip }}). `SKILL.md` sits at the top
   level of the archive, next to the `references` folder.
2. On a computer, open [gemini.google.com](https://gemini.google.com), or open the Gemini app on
   a Mac. In the sidebar, select **Customize** (if you don't find it, select **More** first), then
   **Skills** at the top.
3. Select **Create**, then **Upload**.
4. Choose `slop-check-lite.zip` and select **Open**.
5. Skip the optional extra files and select **Upload**.
6. Review the skill and select **Create**.
7. Check that the skill is active. If it is inactive, open it and select **More**, then
   **Activate**.

If Gemini rejects the archive, unzip it into a folder named `slop-check` and upload that folder in
step 4. The folder name must match the skill name:

```sh
unzip slop-check-lite.zip -d slop-check
```

Before you upload a folder, remove hidden files such as `.DS_Store`; Google warns that they can
make the upload fail. Gemini allows up to 100 active skills at a time. To update the skill later,
open it and select **More**, then **Replace skill**, and upload the whole package again.

### What works here

| Feature | Behavior |
|---|---|
| Automatic use | Gemini uses active skills when a request matches. It decides from the skill's name and description only. |
| Explicit call | Type `/slop-check` in the chat (or `@slop-check` with the updated shortcut) and select the skill. Use this for audits. |
| Bundled scripts | Google accepts `.py` and `.sh` files in a skill but does not say that chat runs them; in tests they did not run. The lite package leaves them out, and the skill works without them. |
| Reference files | Gemini opens them only when it decides it needs them. `SKILL.md` carries everything an audit needs. |
| Language | Google's Workspace admin guide says skills in the Gemini app are initially available in English only. |

For an audit, call the skill explicitly and choose a higher thinking level in the model menu. If
the answer has no verdict line, ask again at a higher thinking level. Run audits in a normal chat:
Google says skills do not yet work with Canvas and Deep Research. Task mode uses the same skills
and can run code on a remote computer, but Google does not say whether it runs skill scripts
there, so that is unverified. Task mode needs a personal Google Account. Outside Australia,
Canada, India, Japan, South Korea and the US it needs a Google AI Pro or Ultra subscription, and it
is not available in the European Economic Area, Switzerland, the United Kingdom and Nigeria.

## Work and school accounts

Google's Workspace admin guide lists skills in the Gemini app as available for Workspace accounts,
in English and with manual file uploads. The skills page of the Gemini Apps Help no longer
describes availability for work and school accounts as coming soon, while Google's page on the
transition from Gems still says that availability will expand to them soon. Task mode is not
available with work and school accounts. Administrators control skills through the **Gemini app
access settings**, for the whole organization or for organizational units. The upload steps are
the same as above.

Gems stay available in Workspace until the automated move, which starts no sooner than March 2027
for business and enterprise editions and June 2027 for education.

Skills in Google Workspace Studio and in the Gemini side panel of Gmail, Docs, Slides, Drive and
Chat cannot take the package: Workspace Studio does not let you attach local or reference files to
a skill. For work accounts, use the Gemini app.

## Gemini Enterprise

Gemini Enterprise has its own skill store, and skills are off until an administrator turns them on.
In the Google Cloud console, the administrator goes to the Gemini Enterprise page, selects the app,
then **Configurations** and the **Feature Management** tab, and turns on **Enable skills**.
Standard, Plus and pay-as-you-go editions can upload skills. Frontline users can use skills but not
upload them.

1. Download [slop-check.zip]({{ site.download_zip }}). Gemini Enterprise accepts an archive with
   exactly one `SKILL.md`, either at the root of the archive or inside a single top-level folder
   whose name matches the skill name. The zip works as it is, and so would
   [slop-check-flat.zip]({{ site.download_flat_zip }}).
2. Sign in to the Gemini Enterprise web app and select **Skills** in the navigation menu.
3. Select the add icon, then **Upload skill**.
4. Drag in `slop-check.zip` or browse for it, then select **Import**. Gemini Enterprise turns the
   skill on by default.

### What works here

| Feature | Behavior |
|---|---|
| Automatic use | Gemini Enterprise uses the skill when a request matches its description. |
| Explicit call | Type `/` or `@` in the chat box and select slop-check, or write "Use the slop-check skill to audit this text." A prompt cannot call an agent and a skill together. |
| Bundled scripts | Google documents Python and Bash execution for skill scripts. The Python version and network access are not documented. |
| Reference files | Loaded on demand. |

Google says skill availability in a chat depends on the selected model. If slop-check does not
appear in a chat, switch the model.

Google lists these limits and restrictions:

- `name` up to 64 characters, `description` up to 1,024 characters and the Markdown body of
  `SKILL.md` up to 500,000 characters. Longer values make the upload fail.
- Archives up to 100 MB compressed and uncompressed, 100 files and 10 levels of folder nesting.
- Skills are not available for use with agents.
- Skills work best with Canvas when a skill has only one `SKILL.md` file. slop-check also has
  reference files and scripts, so run audits in a normal chat.

## Gemini CLI

Since 2026-06-18, unpaid-tier and Google One users use Antigravity CLI instead
of Gemini CLI, as a banner on the Gemini CLI documentation says. Follow the
[Antigravity](#antigravity) steps in that case.

Gemini CLI discovers skills at the start of each session and asks for your confirmation before it
activates one.

1. Download [slop-check.zip]({{ site.download_zip }}).
2. For all your projects, unzip it into your user skills folder:

   ```sh
   mkdir -p ~/.gemini/skills
   unzip slop-check.zip -d ~/.gemini/skills
   ```

   For one project, unzip it into `.agents/skills/` (or `.gemini/skills/`) in the project folder.
   `~/.agents/skills/` works as an alias for the user folder.

   Gemini CLI can also do this for you. Unzip the package anywhere, then run
   `gemini skills install ./slop-check` to install the skill from that local folder, or
   `gemini skills link ./slop-check` to link it with a symlink instead of copying it. Add
   `--scope workspace` to install it for the current project only.
3. Start a session and run `/skills list`. The list should contain `slop-check`. In a running
   session, `/skills reload` picks up a new skill.
4. Ask for an audit. Approve the activation prompt when Gemini CLI asks to use the skill.

### What works here

| Feature | Behavior |
|---|---|
| Automatic use | Gemini CLI activates the skill when a request matches its description, after you approve it. |
| Explicit call | Name the skill in the request, for example "Use the slop-check skill to audit README.md." Gemini CLI documents no slash command for a single skill. |
| Bundled scripts | They run on your computer after your approval, with your Python (3.10 or newer). The checker needs no network. |
| Reference files | On activation, Gemini CLI gets read access to the skill folder and reads the files as it needs them. |

## Antigravity

Since 2026-06-18, Google AI Pro and Ultra subscribers and users of Gemini Code Assist for
individuals use Antigravity CLI instead of Gemini CLI. Agent Skills carry over. Enterprise Code
Assist licenses and API-key users keep Gemini CLI.

1. Download [slop-check.zip]({{ site.download_zip }}).
2. For all workspaces, unzip it into `~/.gemini/config/skills/`. Antigravity CLI, the Antigravity
   App and the Antigravity IDE all read this folder:

   ```sh
   mkdir -p ~/.gemini/config/skills
   unzip slop-check.zip -d ~/.gemini/config/skills
   ```

   Antigravity CLI also reads `~/.gemini/skills/` and `~/.gemini/antigravity-cli/skills/`, which
   the App does not. The Antigravity IDE also reads the older `~/.gemini/antigravity/skills/`.
3. For one project, unzip it into `.agents/skills/` at the workspace root. Antigravity also reads
   `.agents/skills/` in each parent folder up to the repository root, and still reads the older
   `.agent/skills`. Antigravity does not read `.gemini/skills/` inside a project; move an existing
   copy to `.agents/skills/`.
4. In a running Antigravity CLI session, run `/skills reload` or start a new conversation.

### What works here

| Feature | Behavior |
|---|---|
| Automatic use | On every turn the agent sees the names and descriptions of all skills and reads `SKILL.md` when one fits. |
| Explicit call | Type `/slop-check` in Antigravity CLI or in the Antigravity App. |
| Bundled scripts | The agent can run them on your computer, with your Python (3.10 or newer). |
| Reference files | The agent reads them as it needs them. |
