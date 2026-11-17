---
title: No skill support
eyebrow: Setup · Fallback
lead: Assistants without skills can still apply slop-check. The file system-prompt.md holds the skill instructions, the report format and a condensed pattern catalog in one Markdown document.
description: Use slop-check's system-prompt.md as standing instructions in assistants that do not support Agent Skills.
aside: setup
---

`system-prompt.md` is sized to fit a system prompt or custom instructions. It runs without
scripts: the assistant applies the catalog itself, as the skill does when it cannot run commands.
The condensed catalog gives each pattern its rule and one example per language. The full detail,
with every example phrase, word list and rubric, is in [knowledge.md]({{ site.knowledge_url }}) on
the `dist` branch. Attach it as a knowledge file where your assistant supports one.

## Steps

1. Download [system-prompt.md]({{ site.download_prompt }}) from the latest release.
2. Find the place where your assistant keeps standing instructions. Products use different names
   for it, such as system prompt or custom instructions.
3. Paste the whole file into that field.
4. If the field has a length limit that the file exceeds, store the file where the assistant can
   read it, such as project files or uploaded documents. Then write one line of instructions: "Apply
   system-prompt.md to every text you check or write."
5. Where the assistant accepts knowledge files, add `knowledge.md` as well.
6. Start a new conversation and run the check from the
   [setup overview]({{ '/setup/' | relative_url }}#check-that-it-works).

## Through an API

Send the content of `system-prompt.md` as the system message of each request. For deterministic
results on the rule-based patterns, run the command-line tool first and pass its JSON result to the
model with the text.

## Limits of the fallback

- The assistant evaluates every pattern by reading. Results vary more between runs than results
  of the bundled checker, which counts rule-based patterns deterministically.
- The condensed catalog trades detail for size. Borderline cases are judged with less evidence than
  the skill has, unless `knowledge.md` is attached.
- Updates do not arrive by themselves. Download the file again after a new release.

For deterministic results, run the [command-line tool]({{ '/usage/' | relative_url }}#command-line).
