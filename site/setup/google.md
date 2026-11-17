---
title: Google
eyebrow: Setup · Gemini
lead: Install slop-check in the Gemini app, in Gemini Enterprise, in Gemini CLI and in Antigravity CLI.
description: Upload the slop-check skill to the Gemini app or Gemini Enterprise, deactivate a converted slop Gem, and add the skill folder to Gemini CLI or Antigravity CLI.
aside: setup
checked: 2026-11-17
verified:
  - title: Create and manage skills for Gemini Apps (Gemini Apps Help)
    url: https://support.google.com/gemini/answer/17094296?hl=en
  - title: About the transition from Gems to skills (Gemini Apps Help)
    url: https://support.google.com/gemini/answer/18560919?hl=en
  - title: Gemini skills overview (gemini.google)
    url: https://gemini.google/overview/skills/
  - title: About the transition from Gems to skills (Google Workspace)
    url: https://knowledge.workspace.google.com/p/gems-migration
  - title: Prepare your organization for the transition to skills (Google Workspace Admin)
    url: https://knowledge.workspace.google.com/admin/generative-ai/gemini-app/prepare-for-the-transition-to-skills
  - title: Create and manage skills (Gemini Enterprise)
    url: https://docs.cloud.google.com/gemini/enterprise/docs/skills
  - title: Agent Skills (Gemini CLI documentation)
    url: https://geminicli.com/docs/cli/skills/
  - title: Transitioning Gemini CLI to Antigravity CLI (Google Developers Blog)
    url: https://developers.googleblog.com/an-important-update-transitioning-gemini-cli-to-antigravity-cli/
  - title: Migrating from Gemini CLI (Antigravity documentation)
    url: https://antigravity.google/docs/cli/gcli-migration
---

The package meets the rules of the Gemini app, which are the strictest of the runtimes it
supports: a lowercase folder name with hyphens that matches the skill name, `SKILL.md` in the
folder root, text files only, and scripts that run without internet access.

## Gems and skills

Google is replacing Gems with skills. For personal accounts, Gems became read-only on
2026-11-17 and are removed on 2026-12-17; Google recreates each Gem as a skill. Work and school
accounts follow in 2027.

If you built a slop-check Gem before, its converted copy is a second slop-check skill. Install the
package as described below and keep the converted skill inactive. To deactivate it, open it on
the Skills page and select **More**, then **Deactivate**.

## Gemini app

You need to be 18 or older and signed in. Skills are available without a Google AI subscription.
The upload steps below are written for a computer; the help page does not describe uploading
from the mobile app.

1. Download [slop-check.zip]({{ site.download_zip }}) and unzip it. You get a folder named
   `slop-check`.
2. Open [gemini.google.com](https://gemini.google.com) on a computer. Select **Customize** in the
   sidebar (or **More**, then **Customize**), then **Skills** at the top. Google's overview page
   calls the same place **Settings > skills**.
3. Select **Create**, then **Upload**.
4. Select the `slop-check` folder and confirm with **Open**. The dialog also accepts a `.zip`
   with `SKILL.md` in its main folder; the folder is the safer choice for this package.
5. Skip the optional extra files and select **Upload**.
6. Review the skill and select **Create**.
7. Check that the skill is active. If it is not, open it and select **More**, then **Activate**.
   Gemini uses active skills automatically when a request matches.

Remove hidden files such as `.DS_Store` from the folder before you upload; they make the upload
fail. The package itself contains none. Gemini allows up to 100 active skills at a time.

## Work and school accounts

Skills are available in the Gemini app for Google Workspace accounts in English, with manual file
uploads. Administrators control them through the **Gemini app access settings**, for the whole
organization or for organizational units. The upload steps are the same as above. Gems stay
available in Workspace until the automated move, which starts no sooner than March 2027 for
business and enterprise editions and June 2027 for education.

## Gemini Enterprise

Gemini Enterprise has its own skill store. An administrator must turn on the skills feature first.
Standard, Plus and pay-as-you-go editions can upload skills; Frontline users can use skills but not
upload them.

1. Download [slop-check.zip]({{ site.download_zip }}). Gemini Enterprise accepts an archive with
   `SKILL.md` inside a single top-level folder, so the zip works as it is.
2. Sign in to the Gemini Enterprise web app and select **Skills** in the navigation menu.
3. Select the add icon, then **Upload skill**.
4. Drag in `slop-check.zip` or browse for it, then select **Import**.

## Gemini CLI

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
3. Start a session and run `/skills list`. The list should contain `slop-check`.
4. Ask for an audit. Approve the activation prompt when Gemini CLI asks to use the skill.

## Antigravity CLI

Since 2026-06-18, Google AI Pro and Ultra subscribers and users of Gemini Code Assist for
individuals use Antigravity CLI instead of Gemini CLI. Agent Skills carry over. Enterprise Code
Assist licenses and API-key users keep Gemini CLI.

1. For all projects, keep or place the folder in `~/.gemini/skills/slop-check/`. Antigravity CLI
   reads global skills from your home directory.
2. For one project, put the folder in `.agents/skills/slop-check/`. Antigravity CLI does not read
   `.gemini/skills/` inside a project; move an existing copy to `.agents/skills/`.
