---
title: No skill support
eyebrow: Setup · Fallback
lead: Assistants without skills can still apply slop-check. The file system-prompt.md holds the skill instructions and every reference in one Markdown document.
description: Use slop-check's system-prompt.md as a system prompt, custom instructions or project instructions in assistants that do not support Agent Skills.
aside: setup
---

The export contains the instructions of `SKILL.md` followed by all reference files, including the
full pattern catalog. It runs without scripts: the assistant applies the catalog itself, as the
skill does when it cannot run commands.

## Steps

1. Download [system-prompt.md]({{ site.download_prompt }}) from the latest release.
2. Find the place where your assistant keeps standing instructions. Depending on the product it is
   called system prompt, custom instructions, project instructions or agent instructions.
3. Paste the whole file into that field.
4. If the field has a length limit that the file exceeds, store the file where the assistant can
   read it, such as project files or a knowledge base. Then write one line of instructions: "Follow
   system-prompt.md for every text you review, rewrite or write."
5. Start a new conversation and run the check from the
   [setup overview]({{ '/setup/' | relative_url }}#check-that-it-works).

## Through an API

Send the file content as the system message of each request. Models with a small context window
may not fit the full catalog; in that case use the command-line tool for the rule-based patterns
and ask the model only for the rewrite.

## Limits of the fallback

- The assistant evaluates every pattern by reading. Results vary more between runs than results
  of the bundled checker, which counts rule-based patterns deterministically.
- The file is large, about 180 kB. It takes up part of the context window in every conversation.
- Updates do not arrive by themselves. Download the file again after a new release.

For deterministic results, run the [command-line tool]({{ '/usage/' | relative_url }}#command-line).
