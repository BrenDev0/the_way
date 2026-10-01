"""The house design system.

This is the actual payload of the html_builder assistant. A model asked for "a styled
report" reaches for the median of its training data -- Arial, a centred h1, a table with
1px grid borders -- because "styled" constrains nothing. What follows constrains it:
specific values, named bans, and per-archetype playbooks.

Edit this file to change the house style globally. A user can override it by writing
design/brand.md in their .the_way workspace project, which both passes read before
deciding anything.
"""

DESIGN_SYSTEM = """
=== HOUSE DESIGN SYSTEM (non-negotiable) ===

Professional-looking HTML is not decoration added at the end. It is four things done
deliberately: space, type, restraint, and detail. Amateur output fails at all four in the
same predictable ways. Every rule below exists to block a specific one of those failures.

--- 1. TOKENS FIRST ---
Every stylesheet opens with a :root block of custom properties. Nothing below it may use
a raw hex colour, a raw px font-size, or an arbitrary margin. If a value is worth using
twice it is a token.

    :root {
      --ink:        #16171a;   /* near-black, never #000 */
      --ink-muted:  #5b6068;
      --ink-faint:  #8a9098;
      --ground:     #fbfbf9;   /* off-white, never #fff for the page */
      --surface:    #ffffff;   /* cards sit ABOVE the ground */
      --line:       #e5e4df;   /* hairlines */
      --accent:     #1f5f4b;   /* exactly one accent */
      --accent-soft:#e8f0ed;
      --radius:     10px;
      --measure:    68ch;
      --step-0:     1rem;      /* body */
      --step-1:     1.25rem;
      --step-2:     1.6rem;
      --step-3:     2.1rem;
      --step-4:     2.9rem;
      --step-5:     3.9rem;    /* hero only */
      --space-1: 4px;  --space-2: 8px;  --space-3: 16px;
      --space-4: 24px; --space-5: 40px; --space-6: 64px;
      --space-7: 96px; --space-8: 144px;
    }

Spacing is ONLY ever a --space token. This single rule is what separates composed
layouts from ones that drift.

--- 2. TYPE ---
- Never leave the browser default. Never Arial, Helvetica, Times New Roman, or a bare
  sans-serif/serif keyword as the primary face.
- Pick a real pairing. Either a well-set system stack:
      -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif
  or a Google Fonts pair loaded with <link rel="preconnect">. Good pairings:
      Reports/editorial : Fraunces or Source Serif 4 headings + Inter body
      Corporate/data    : Inter or Geist throughout, weight contrast only
      Landing/product   : Space Grotesk or Satoshi headings + Inter body
      Technical         : IBM Plex Sans + IBM Plex Mono for figures
- Scale is ratio-based (the --step tokens), never a pile of arbitrary sizes.
- Body line-height 1.6-1.7. Heading line-height 1.05-1.2. They are not the same number.
- Large headings get letter-spacing: -0.02em to -0.03em. Small caps labels get +0.08em.
- Body text never exceeds --measure (about 68 characters). A full-width paragraph on a
  1440px screen is the single loudest amateur signal.
- Weight contrast beats size contrast. 400 body against 600/700 headings.

--- 3. COLOUR ---
- Never pure #000 on pure #fff. Near-black ink on a warm off-white ground.
- ONE accent colour. It marks the single most important thing per view and nothing else.
  Two accents is a design; three is a mistake.
- 60/30/10: ground / ink and surfaces / accent.
- Borders are hairlines (1px, --line), not visible frames.
- Shadows, if any, are large and faint: 0 1px 2px rgba(0,0,0,.04), 0 8px 24px rgba(0,0,0,.06).
  Never a dark blur pinned tight to the element.
- Support dark mode with @media (prefers-color-scheme: dark) redefining ONLY the tokens.

--- 4. SPACE ---
- Whitespace is the primary signal of quality. When something looks cheap, the fix is
  almost always more space, not more decoration.
- Desktop section padding: --space-7 to --space-8 vertical. Not 20px.
- Space belongs between groups, not inside them: an eyebrow sits 8px from its heading and
  the pair sits 64px from the block above. Related things touch; unrelated things do not.
- Set a page container: max-width 1120px (marketing) or 880px (documents), centred, with
  --space-5 side padding that survives on mobile.

--- 5. HIERARCHY AND STRUCTURE ---
- Every major block opens with an eyebrow (small, uppercase, letter-spaced, --ink-faint or
  --accent) above its heading. This one pattern does more for perceived polish than
  anything else on this list.
- Headings carry a deck/standfirst: one --step-1 line in --ink-muted under the h1/h2.
- Use a real grid. `display: grid` with named areas or asymmetric columns
  (e.g. grid-template-columns: 1.4fr 1fr). A page that is only stacked full-width blocks
  reads as a document dump regardless of its colours.
- Vary rhythm: full-bleed band, then contained text, then a two-column split. Alternating
  section backgrounds (--ground / --surface) is the cheapest way to create structure.

--- 6. DETAIL (what actually reads as "professional grade") ---
- Numbers use font-variant-numeric: tabular-nums. Always. Figures that don't align in a
  column look broken.
- Tables: no vertical rules, no full grid. Hairline row separators only, a stronger rule
  under the header, uppercase letter-spaced header labels in --ink-muted, numeric columns
  right-aligned, generous cell padding (12px 16px), and a subtle row hover.
- Interactive elements get :hover AND :focus-visible states. Focus ring:
  outline: 2px solid var(--accent); outline-offset: 2px.
- transition: 150ms ease on colour/transform for anything hoverable. Nothing longer than 250ms.
- Images/figures get border-radius: var(--radius) and a caption in --step-0 --ink-muted.
- Icons, if used, are inline SVG with stroke-width 1.5 and currentColor. Never emoji.
- Print stylesheet for reports: @media print { } that drops backgrounds, forces black ink,
  and sets page-break-inside: avoid on tables and figures.
- Every page may be converted to PDF or PNG, where there is no viewport and nothing
  scrolls. So that it survives paper unchanged:
  - Size sections by their content. Never height: 100vh or a fixed height on anything
    that holds text; a hero that should be tall gets min-height in rem, not vh.
  - No fixed or minimum widths wider than the content needs: max-width plus width: 100%,
    never width: 1200px or min-width on a layout container.
  - Grid and flex children that hold text get min-width: 0, so a long word or a wide table
    wraps instead of pushing the layout past the edge. Wide tables sit in a wrapper that
    lets them shrink, and their cells wrap.
  - No overflow: hidden on html, body or a section of text -- only on decorative shapes.
  - No position: fixed or sticky for anything the reader needs.

--- 7. BANNED (these are what "plain" is made of) ---
- Arial / Helvetica / Times / default serif as the primary face
- Pure black on pure white
- Centred body copy, or centring everything by default
- Full-viewport-width paragraphs with no max-width
- The purple-to-blue diagonal gradient hero
- Tables with a complete 1px border grid
- box-shadow: 0 0 10px rgba(0,0,0,0.5) and friends
- Emoji standing in for icons or bullets
- <center>, <br> for spacing, inline style= attributes for layout
- Bootstrap-default-looking pill buttons in primary blue
- More than one accent colour
- Placeholder text left in the output ("Lorem ipsum", "Your text here")

--- 8. OUTPUT SHAPE ---
- ONE self-contained .html file unless the caller asked otherwise: <style> in <head>, no
  external CSS or JS files, no build step. It must open correctly from a double-click and
  survive being emailed.
- Web fonts via <link> to Google Fonts are allowed and encouraged; everything else is
  inline. Never reference an image file that does not exist -- use inline SVG, a CSS
  gradient, or omit the image.
- Semantic HTML: <header> <main> <section> <article> <figure> <table>. Headings descend in
  order without skipping.
- <meta name="viewport" content="width=device-width, initial-scale=1"> and a real mobile
  breakpoint (@media (max-width: 768px)) that collapses grids to one column and steps the
  type scale down. Never ship a desktop-only page.
- A <title> that names the document.
"""


ARCHETYPES = {
    "report": """
--- ARCHETYPE: REPORT / ANALYSIS DOCUMENT ---
Read like a consultancy deliverable, not a webpage.
- Cover block: eyebrow (client or category), --step-4/5 title, one-line deck, then a
  hairline rule and a metadata row (date, author, period) in small --ink-muted caps.
- Lead with an executive summary in a tinted --accent-soft panel before any detail.
- Key figures go in a KPI row: 3-4 cells, --step-4 tabular-nums value, small uppercase
  label beneath, delta in --accent or a muted red. Separated by hairlines, not boxes.
- Numbered sections (01, 02, 03) with the number set large and faint beside the heading.
- Pull quotes / callouts: a left border 3px --accent, --step-1 italic, generous padding.
- Every table follows the table rules above. Every chart is inline SVG or a CSS bar row --
  never a script that fetches a charting library at runtime.
- Close with a methodology/sources block in smaller type.
- Ship the @media print block.
""",
    "landing": """
--- ARCHETYPE: LANDING PAGE ---
Sell one thing. Structure is: hero -> proof -> value -> objection -> close.
- Hero: eyebrow, --step-5 headline with tight negative tracking, --step-1 subhead capped at
  ~55ch, ONE primary CTA plus one quiet secondary link. Asymmetric -- content 1.4fr against
  a visual 1fr -- not a centred stack.
- Immediately under the hero: a muted proof strip (logos as text in --ink-faint, or a
  one-line stat row). Fills the trust gap before the first scroll.
- Feature blocks alternate image/text sides. Three max. Each gets an eyebrow, a heading,
  two lines of copy. Not a bullet list.
- One dark band somewhere in the middle (invert the tokens) for testimonial or metrics.
  Rhythm break; makes the whole page feel designed.
- Primary CTA button: solid --accent, --radius, 14px 28px padding, 600 weight, hover lifts
  translateY(-1px) with a slightly stronger shadow.
- Footer: multi-column, hairline top rule, --ink-faint links.
""",
    "dashboard": """
--- ARCHETYPE: DASHBOARD / ONE-PAGER ---
Density with discipline.
- 12-column CSS grid; cards span it asymmetrically. Never a uniform 3x3 of identical boxes.
- Cards: --surface on --ground, 1px --line, --radius, --space-4 padding. Card header is a
  small uppercase label, not an h2.
- One hero metric materially larger than the rest. If everything is emphasised, nothing is.
- Charts are inline SVG using --accent plus greys. Gridlines are --line at 1px, axis labels
  --ink-faint, no chart junk, no 3D, no legend if the data can be labelled directly.
- All figures tabular-nums, right-aligned in columns.
""",
    "article": """
--- ARCHETYPE: ARTICLE / LONGFORM ---
Reading comfort above all.
- Single column at --measure, centred. Body --step-1 (not --step-0) for longform, 1.7
  line-height.
- Drop the standard header: eyebrow, --step-4 title, deck, byline row with a hairline.
- Figures and pull quotes break out wider than the measure (a negative-margin bleed) to
  create rhythm.
- Paragraph spacing over indentation. No justified text.
- Optional: a thin reading-progress bar or a sticky minimal header. Nothing more.
""",
}


def archetype_guidance(page_type: str) -> str:
    """The playbook for a page type, falling back to the report rules -- the strictest set,
    and the safest default for anything document-shaped."""
    return ARCHETYPES.get(page_type, ARCHETYPES["report"])
