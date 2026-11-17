## What changed

<!-- One or two sentences. For a pattern: the mechanism it detects and why it is distinct. -->

## Pattern ids

<!-- New or edited ids, e.g. `antithesis-template`. Write "none" if no pattern changed. -->

## Sources

<!-- New or used source ids with their URLs. Sources that copy each other count as one. -->

## Examples added

<!-- Languages and number of positive and negative examples per language. -->

## Checklist

- [ ] `slopcheck-dev validate` passes locally
- [ ] `slopcheck-dev check-fixtures` passes locally
- [ ] `pytest` passes locally
- [ ] Negative examples are realistic near misses in the target language, not unrelated sentences
- [ ] Examples were collected from texts in that language, not translated from another language
- [ ] New patterns are `observation` or `candidate`; nothing declares `core`
- [ ] Findings describe style patterns and make no claim that a text was written by an AI
- [ ] If an AI agent produced this change, its commits carry the agent's own identity
