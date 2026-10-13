"""The kit's hardened print CSS (the-way-kit, skills/output-documents/engine/render.js),
injected at render time rather than inherited from the page.

How a document prints is the renderer's job, not the document's: injected here, any page
prints right -- including ones written before a rule existed. Idempotent: a page that
already carries these rules gets the same result. The class names (.cover, .route, .tier,
...) are the kit's document template; on any other page those rules match nothing.
"""

# The column a scroll PDF is laid out in: a phone, as messaging apps show it.
SCROLL_WIDTH = 440
# The screen a paginated document is laid out on before printing.
PAGED_VIEWPORT_WIDTH = 900
# What marks a page as a kit document: its core layer's own header.
KIT_CORE_MARKER = "SIS_GEN_DAT_Nucleo"

PRINT_CSS = """
@media print{
  @page{margin:11mm}
  html,body{background:#fff}
  body{font-size:10.5pt;line-height:1.5}

  /* forced colour: without it dark blocks print white */
  .cover,.auth,.close,footer,.warranty,.route.hero .route-h,
  .val tr.total td,.val tr.sum td,.tag,.seal,.cta,.tier.on,.call,.why,.outs{
    -webkit-print-color-adjust:exact;print-color-adjust:exact}

  /* nothing splits inside */
  section,.route,.tier,.call,.val,.warranty,.outs,.out,.step,.term,
  .act,.meta,.auth,.close,footer,tr{break-inside:avoid;page-break-inside:avoid}

  /* a heading never sits alone at the foot of a page */
  h1,h2,h3,.eye{break-after:avoid;page-break-after:avoid}
  .eye+h2,.route-h,.tw{break-before:avoid;page-break-before:avoid}

  p,li,.term .v,.out span{orphans:3;widows:3}

  section{padding-top:26px;padding-bottom:26px}
  .cover{padding-top:0}
  :root{--pad-sec:26px}

  footer{break-before:avoid;page-break-before:avoid}

  .rv{opacity:1!important;transform:none!important}
  .cta{box-shadow:none;border:1.5pt solid var(--brand)}
  .route:hover,.tier:hover{transform:none;box-shadow:none}
  a[href^="http"]{text-decoration:none}
}

/* one scroll: the document is a single page, so the page-break gates are in the way */
@media print{
  html.scroll .doc{max-width:none}
  html.scroll section{padding-top:34px;padding-bottom:34px}
  html.scroll *{break-inside:auto!important;page-break-inside:auto!important}
}

/* Tables in a scroll. A wide table that scrolls sideways on screen is cut off on paper,
   silently: a PDF cannot scroll. In scroll mode every table becomes stacked cards -- one
   per row, the first cell as its title, every other cell labelled from the header. */
@media print{
  html.scroll table{width:100%!important;min-width:0!important}
  html.scroll thead{
    position:absolute;width:1px;height:1px;overflow:hidden;
    clip:rect(0 0 0 0);clip-path:inset(50%);white-space:nowrap;
    border:0;padding:0;margin:-1px}
  html.scroll tbody,html.scroll tbody tr,html.scroll tbody td{display:block;width:100%}
  html.scroll tbody tr{margin-bottom:10px;break-inside:avoid;page-break-inside:avoid}
  html.scroll tbody td{
    display:flex;justify-content:space-between;align-items:baseline;
    gap:14px;text-align:left;white-space:normal;word-break:break-word}
  html.scroll tbody td:first-child{display:block;font-weight:700}
  html.scroll tbody td::before{content:attr(data-t);font-weight:600;opacity:.6;flex:0 0 auto}
  html.scroll tbody td:first-child::before{content:none}
}
"""

# A scroll is one page: the 11 mm margin above would narrow the column, the real height
# would exceed the measured one, and the close would be cut off.
SCROLL_PAGE_CSS = "@page{margin:0}"

# Run by Playwright, not the page: reveal-on-scroll content shown, the scroll class on,
# and each table cell labelled from its header unless the template already did.
PREPARE_SCROLL = """
() => {
  document.querySelectorAll('.rv').forEach(e => e.classList.remove('pre'));
  document.documentElement.classList.add('scroll');
  document.querySelectorAll('table').forEach(table => {
    const labels = [...table.querySelectorAll('thead th, thead td')]
      .map(th => th.textContent.replace(/\\s+/g, ' ').trim());
    if (!labels.length) return;
    table.querySelectorAll('tbody tr').forEach(tr => {
      [...tr.children].forEach((cell, i) => {
        if (i === 0 || cell.hasAttribute('data-t')) return;
        if (labels[i]) cell.setAttribute('data-t', labels[i]);
      });
    });
  });
}
"""


def with_css(html: str, css: str) -> str:
    """The page with `css` after its own styles, so it wins the cascade. Put into the
    HTML before loading: Playwright's add_style_tag waits on a script, and scripts are off."""
    block = f"<style>{css}</style>"
    lower = html.lower()
    at = lower.rfind("</body>")
    if at == -1:
        at = lower.rfind("</head>")
    if at == -1:
        return html + block
    return html[:at] + block + html[at:]
