# Rewrite procedure

A rewrite is surgical. It removes the flagged patterns and leaves everything else as the
author wrote it. Use it only when the user asks for a rewrite or a clean-up.

## 1. Audit first

Run the audit of `references/audit-procedure.md` on the original text, unless an audit of the
same text is already in the conversation. Note the verdict and score.

The edit set is:

- every hit of a triggered finding
- every hit of a triggered observation, when the fix is small and clearly improves the
  sentence
- hits of scored patterns below their threshold, only when the user asked for a thorough
  clean-up

If the audit found nothing, return the text unchanged with a note that no scored pattern
triggered, unless the user insists on edits.

## 2. Plan each edit

For each passage in the edit set, read the pattern's fix in `references/text-patterns.md` and
choose the smallest change that removes the pattern:

- Delete padding that carries no information: generic openers, closing summaries, service
  phrases addressed to the reader, empty disclaimers, announcements of a point.
- Replace inflated or stock wording with the plain statement the sentence already makes.
- Split a template construction into a direct claim. If the text gives a real reason or
  example, keep it.
- Replace dash chains with ordinary punctuation. Turn bold-lead bullets and decorative emoji
  into plain list items.
- For vague attributions ("studies show", "Experten zufolge"), keep the claim and drop the
  hollow attribution, or keep it unchanged and mark it in the change list as needing a source.

Never invent facts, numbers, names, dates, quotes or sources to make a passage concrete. If
the fix needs a detail the text does not contain, ask the user for it or cut the passage;
when neither fits, leave the passage as it is.

## 3. Keep what is not flagged

- Meaning: every claim of the original survives unless it was pure padding.
- Facts: numbers, dates, names, prices, places, links and quoted material stay exactly as they
  were.
- Terminology: keep technical terms and product names, as well as words the text defines,
  even when a synonym would read more smoothly.
- Voice: keep person and tense, the register, the form of address (du or Sie; first names or
  titles) and regional spelling (British or American English; Swiss "ss"). Outside the
  flagged spans, keep the author's sentence habits.
- Structure: keep headings and paragraph order, and keep lists as lists, unless a finding
  concerns them (for example bold-lead bullets or decorative emoji).
- Typography: keep the quotation marks and apostrophes the text uses, straight or curly.
  German texts keep their German quotation marks (shown below).

  ```
  „Zitat“  ‚inneres Zitat‘
  ```

## 4. Length

Stay within 15 percent of the original word count. A rewrite may become shorter when it
removes padding; say so in the result line. Never add sentences to reach a length.

## 5. Audit the result

Run the audit again on the rewritten text, with the script if you can. Edits often create new
patterns: a three-part list where two items stood before, a "not X, but Y" construction, a
new hallmark word, a dash used to join two clauses. Fix every new scored finding and audit
again, at most twice. Report what remains.

## 6. Return the result

Use the rewrite layout of `references/report-format.md`:

1. the complete rewritten text
2. the change list: one entry per edit with old text, new text (or deleted), pattern ID and a
   short reason
3. the result line with verdict and score before and after

Keep the change list in the order the edits appear in the text. When one edit removes hits of
two patterns, name both IDs.
