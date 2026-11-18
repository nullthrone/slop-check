---
title: No skill support
eyebrow: Setup · Fallback
lead: Assistants without skills can still apply slop-check from a single file. Three exports cover short instruction fields, knowledge files and API system messages.
description: Use slop-check's instructions.md, knowledge.md or system-prompt.md in assistants and APIs that do not support Agent Skills.
aside: setup
checked: 2026-11-17
verified:
  - title: Using Agent Skills with the API (Claude Platform Docs)
    url: https://platform.claude.com/docs/en/build-with-claude/skills-guide
  - title: Skills (OpenAI API documentation)
    url: https://developers.openai.com/api/docs/guides/tools-skills
  - title: Skills in declarative agents (Microsoft Learn)
    url: https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/declarative-agent-skills
  - title: Custom instructions (Mistral Docs)
    url: https://docs.mistral.ai/le-chat/knowledge-integrations/custom-instructions
---

Check first whether your product takes a skill after all. The
[capability matrix]({{ '/setup/' | relative_url }}#capability-matrix) lists the products that do.
The exports have no script and judge every pattern by reading, so use them where no skill route
exists.

## Which file to use

| File | Size | Use it for |
|---|---|---|
| [instructions.md]({{ site.download_instructions }}) | at most 7,500 characters | Instruction fields of about 8,000 characters, such as ChatGPT project instructions, the instructions of a Microsoft 365 Copilot declarative agent, or a Vibe Work skill form that takes text only |
| [knowledge.md]({{ site.download_knowledge }}) | about 340 KB | Knowledge files and project files |
| [system-prompt.md]({{ site.download_prompt }}) | about 80,000 characters | API system messages and instruction fields without a tight limit |

`instructions.md` holds the audit procedure, the report layout, short rewrite and writing rules
and the scored patterns in compact form. `knowledge.md` holds the skill instructions with every
reference file, which includes the complete catalog with all example phrases, word lists and
rubrics. `system-prompt.md` holds the skill instructions, the report format and a condensed
catalog that gives each pattern its rule and one example per language.

`system-prompt.md` does not fit typical instruction fields. Microsoft 365 Copilot limits
declarative agent instructions to 8,000 characters. ChatGPT project instructions take about 8,000
characters, a figure from user reports that OpenAI does not publish. Mistral advises a few
sentences for custom instructions in Vibe.

## Instruction field and knowledge file

This is the route for chat products with projects or configurable agents.

1. Download [instructions.md]({{ site.download_instructions }}).
2. Paste the whole file into the instruction field of the project or agent.
3. Where the product accepts knowledge or project files, download
   [knowledge.md]({{ site.download_knowledge }}) and add it. `instructions.md` tells the assistant
   to use it when it is attached.
4. Start a new conversation and run the check from the
   [setup overview]({{ '/setup/' | relative_url }}#check-that-it-works).

Products search knowledge files and hand the matching parts to the model, so the assistant may read
only parts of `knowledge.md`. The instruction field applies to every conversation. That is why
`instructions.md` carries everything an audit needs, and `knowledge.md` adds detail for borderline
cases.

If the field holds fewer characters than `instructions.md`, store `instructions.md` where the
assistant can read it, such as the project files, and write one line into the field: "Apply
instructions.md to every text you check or write." A file found by search is applied less
reliably than text in the field.

## Through an API

The Claude API and the OpenAI API take the skill package itself. Both accept a skill upload and run
the bundled script in a sandboxed container. The [Anthropic]({{ '/setup/anthropic/' | relative_url }})
and [OpenAI]({{ '/setup/openai/' | relative_url }}) guides describe the upload.

For an API without skills, send the content of [system-prompt.md]({{ site.download_prompt }}) as
the system message of each request. For deterministic results on the rule-based patterns, run the
command-line tool first and pass its JSON result to the model with the text.

## Limits of the fallback

- The assistant evaluates every pattern by reading. Results vary more between runs than results
  of the bundled checker, which counts rule-based patterns deterministically.
- `instructions.md` and `system-prompt.md` trade detail for size. Borderline cases are judged with
  less evidence than the skill has, unless `knowledge.md` is attached.
- Updates do not arrive by themselves. Download the files again after a new release.

For deterministic results, run the [command-line tool]({{ '/usage/' | relative_url }}#command-line).
