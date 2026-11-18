# Prevention procedure

Use this procedure when you write a text, create an image or build a web page for the user
and the skill applies. The aim is output that needs no clean-up afterwards.

## Text

1. Before drafting, read `references/prevention-rules-text.md`. The rules are grouped by
   category; rules for scored patterns come first in each group.
2. Collect the concrete material first: the facts, numbers, names, examples and the reader the
   user gave you. Generic filler appears where material is missing.
3. If a detail that carries the text is missing (a date, a price, the actual result), ask one
   short question, or write the text with a clearly marked placeholder such as `[date]`.
   Never fill the gap with invented facts or with general claims.
4. Draft for the genre the user asked for and in the context it will appear in (informal,
   technical, academic, marketing or default). A legitimate use stays legitimate: a long
   manual may need a summary, a medical leaflet may need a warning.
5. Self-audit before you answer. Check the draft against `references/text-patterns.md` with
   `references/audit-procedure.md`, by hand or with the script. Fix every scored finding and
   every triggered candidate that has an easy fix. The draft should come out GREEN.
6. Return the text the user asked for. Do not attach the audit unless the user asks for it;
   if they do, use the layout of `references/report-format.md`.

Avoiding patterns must not make the text stiff. Vary sentence length the way the content
suggests, use ordinary connectors where they carry logic, and keep a natural tone for the
genre.

## Images

Use this part when you call an image model, when the user asks for an image prompt, or when
you direct an image tool in any other way.

1. Read `references/prevention-rules-image.md`.
2. Turn the request into an art-directed prompt. Write it as a short descriptive paragraph
   that names:
   - the subject, taken from the user's topic and shown doing something specific
   - the setting and the time of day
   - the camera position and the lens or framing
   - the composition: where the subject sits in the frame, and what is in front of it and
     behind it
   - the light: where it comes from and what quality it has (hard, soft, diffuse)
   - the palette, taken from the subject and setting
   - textures and materials, including natural skin texture for people
   - the medium or style (photograph, ink drawing, gouache, flat vector)
3. Leave out default-look tokens. Generic quality tags such as "masterpiece", "8k",
   "hyperrealistic" or "trending on artstation" go; each one becomes the concrete property it
   was meant to produce. Generic "cinematic lighting" becomes a named light source. For an
   abstract topic, replace the stock metaphor (glowing brain, robot hand, hooded hacker,
   padlock on a keyboard) with a concrete scene from the user's domain.
4. For people, describe age range and clothing to fit the topic, and avoid defaulting to one
   look for everyone. Ask for visible hands only when they matter, and describe what
   they hold or do.
5. For lettering, keep it to a few words given in quotation marks, or plan to add the text
   after generation.
6. If the user specifies a style, follow it. The rules set the defaults; they never override
   an explicit choice.
7. Generate the image with the prompt. Show the prompt to the user when they asked for a
   prompt, or when they will generate the image elsewhere.
8. If you can see the result, check it against `references/image-patterns.md` with section 9
   of `references/audit-procedure.md`. When a pattern clearly applies and the user did not ask
   for that look, regenerate once with a corrected prompt, or tell the user what you see and
   offer the fix. Stop after two attempts and report what remains.

## Web pages

Use this part when you build, restyle or generate a web page, a landing page or a front-end
component, or when you write the prompt for a site builder.

1. Read `references/prevention-rules-web.md`.
2. Start from the material: who the page is for, what they must do or learn on it, and the
   real assets you have (product, photos, people, numbers, quotes, logos with permission).
   Let that decide the sections and their order instead of a stock landing-page sequence.
3. Set a direction before writing markup: a type pairing and scale, a palette taken from the
   brand or subject, a spacing rhythm, and the one or two places where the layout breaks
   the grid on purpose. Write it down in a few lines when the user will see the code.
4. Never invent trust content. No testimonials, customer logos, ratings, user counts, uptime
   figures or awards that the user did not give you; leave a clearly marked placeholder such
   as `[customer quote]` or leave the section out.
5. Build working, semantic markup: landmarks, one `h1` and a heading outline, real buttons
   and links with targets, labels for inputs, alt text for meaningful images, visible focus,
   sufficient contrast, and motion only where it explains something, honoring
   `prefers-reduced-motion`.
6. If the user specifies a style, a design system or a template, follow it. The rules set
   the defaults; they never override an explicit choice.
7. If you can render the page or see a screenshot, check it against
   `references/web-patterns.md` with section 10 of `references/audit-procedure.md`, fix what
   clearly applies and the user did not ask for, and stop after two rounds.
