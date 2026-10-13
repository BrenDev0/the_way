# Render service · plan

**Status:** phases 1, 2 and 4 done, 13 October 2026. Phase 3 (screenshots to the model)
waits on decision 2.

## Progress

**Phase 1 — done.** `src/render` (`app.py`, `browser.py`, `capture.py`, `config.py`,
`schemas.py`), `src/render_client` (`client.py`, `ports.py`), the Dockerfile `render`
stage, the `render` compose service and network, `RENDER_URL` / `RENDER_SHARED_SECRET` in
settings and `.env.example`. Endpoints: `GET /health`, `POST /png`, `POST /pdf` (the
single-scroll PDF, pulled forward from phase 4 since it is a few lines once the browser is
up).

Verified: 16 tests in `tests/unit/render` (allowlist, JS off, meta refresh, no shared
state, timeout leaves the browser usable, PNG clip and cap, scroll PDF one page and
shrink-to-fit, secret, client fallbacks), passing on Windows and inside the container;
the full unit suite (867) passes in the container. End to end inside compose: the client
on the `render` network got a PNG and a PDF, a wrong secret got 401, Google Fonts load,
and the container cannot resolve `postgres`, `redis`, `s3` or `api` and has none of their
secrets.

Where it differs from the plan:

- **Image size.** Playwright's package is 137 MB (it ships its own Node driver) and the
  headless Chromium 266 MB, plus its system libraries. The stage installs the headless
  shell only (`--only-shell`); the full Chromium would add one more browser that is never
  launched. Still only the `render` image; `api`, `worker`, `migrate` are unchanged.
- **Meta refresh.** Found while building: `<meta http-equiv="refresh">` navigates even with
  scripts off, and an aborted navigation leaves Chromium's error page on screen, which is
  what would have been captured. The tag is stripped before loading, and a page whose URL
  is no longer `about:blank` after loading is refused (422).
- **Network.** The `render` network is a normal bridge (it needs Google Fonts), not
  `internal`. The service is not on `default`, so it cannot reach the database, redis or
  the bucket. Every other address is refused by the browser's request handler; requests to
  the font hosts are fetched with redirects off. A host-level egress allowlist to the two
  font hosts is still open — decision 1 below.
- **Sandbox.** Playwright launches Chromium without its own sandbox by default, which is
  what lets it run as a non-root user in a stock container. The container (no secrets,
  read-only root filesystem, no route to the data stores, memory and CPU limits) is the
  boundary.
- **Short pages.** A real screenshot is never shorter than the screen (900 px); WeasyPrint's
  PNG is trimmed to the content. Expected, and how the page actually looks.

**Phase 2 — done.** `POST /check` (`src/render/checks.py`) opens the page at 375 px and
1440 px and returns findings, each with up to six examples to find it by:

| Check | Width | Catches |
|---|---|---|
| `overflow` | 375 | sideways scroll, naming the outermost elements past the edge (ignoring what a clipping parent cuts) |
| `small_text` | 375 | form fields under 16 px, text under 12 px |
| `css` | 1440 | declarations the browser drops (`CSS.supports`), selectors it cannot parse, `var()` with no fallback and no definition |
| `tokens` | 1440 | colours on screen and spacing (when the page has a `--space-*` scale) that match no `:root` token; a page with no tokens is told so |
| `images` | 1440 | `<img>` without `width`/`height`, images that did not load |
| `contrast` | 1440 | text under WCAG AA (4.5:1, 3:1 for large), skipped over background images |
| `fonts` | 1440 | web fonts that failed, typefaces named but never loaded |

The page builder has a `CheckPage(project, path)` tool (`src/html_pages/check.py`); step 2
of `BUILDER_PROMPT` now calls it, fixes the findings with targeted edits and checks once
more (two checks at most). When the service is down the tool says so and the builder does
the old read-through pass. 11 planted-defect tests (`tests/unit/render/test_checks.py`),
one clean page that must come back clean; 6 tool tests (`tests/unit/html_pages/test_check.py`).

**Phase 4 — done, with the kit's `output-documents` translated.**

- `HtmlToPng` renders through Chromium and falls back to WeasyPrint when the service is
  down, saying so in its result.
- `HtmlToPdf` has `layout: "paged" | "scroll"`. `paged` stays on WeasyPrint for our own
  pages, except a kit document (it carries the kit's core layer, marked
  `SIS_GEN_DAT_Nucleo`): that is paginated in Chromium as the kit's `render.js` does —
  900 px screen, its print CSS, backgrounds printed, Letter or A4 at 11 mm. Measured on
  the kit's `sample.html`: WeasyPrint printed its dark cover white; Chromium prints it as
  designed. With the service down, WeasyPrint is the fallback and the result says so.
- Both paths now print a box that scrolls sideways (`overflow: auto | scroll`) in full,
  so a wide table is scaled to fit instead of losing its right-hand columns
  (`src/exports/css.py`). `scroll` is
  the kit's single-page PDF for WhatsApp, rendered as its `render.js` does: 440 px column,
  the kit's hardened print CSS injected at render time (`src/render/print_css.py`), print
  media emulated before measuring the height, every table turned into stacked cards with
  its header as each cell's label, `@page{margin:0}`, `pageRanges: 1`. Saved as
  `<name>-scroll.pdf`. Longer than one PDF page allows (19 200 px) it is shrunk to fit,
  down to 25 %.
- Both exports, and `CheckPage`, now put a page's linked project stylesheets inside it
  (`ProjectFiles.embed_stylesheets`), the way images already were: a kit document links
  `core.css` and the brand's `tokens.css` (also as `project:Biblioteca/<BRAND>/tokens.css`)
  and rendered unstyled before.
- Found while building: Playwright's `add_style_tag` waits on a script and hangs with
  JavaScript off, so injected CSS goes into the HTML before loading (`with_css`).

## Why

Three gaps, each traced to the code:

1. **The page builder checks its work blind.** Its quality bar ("does not scroll sideways
   at 375 px", "every spacing value is a token", "no banned item appears") is checked by
   the model rereading its own markup (`src/html_pages/prompt.py`, revision pass). Nothing
   measures the page. A rule like *broken CSS raises no error: it swallows rules silently*
   (the kit's `landing-pages/laws.md`) cannot be caught by reading the file.
2. **The PNG is a print layout, not a screen.** `src/exports/render.py` lays the page out
   with WeasyPrint as tall PDF pages, rasterises them with pdfium and stitches them.
   WeasyPrint is not a browser: its support for modern CSS (grid details, `clamp()`,
   `:has()`, `backdrop-filter`, some `position` and `overflow` cases) differs from what a
   person sees in Chrome. `HtmlToPng` promises "how it looks on screen".
3. **No single-scroll PDF.** The kit's `output-documents` makes two PDFs, one paginated
   and one single tall page for messaging apps. WeasyPrint can do the first (it already
   does); the second needs a browser's print-to-PDF of the full height.

What it is **not** for: JavaScript. The builder's rules forbid scripts and draw charts as
inline SVG (`render.py` docstring), so script execution stays off.

## Shape

One codebase, one compose file, its own container and image.

```
the_way_backend/
  src/render/                  new module, imported by nothing in the API image
    app.py                     FastAPI app: POST /check, /png, /pdf; GET /health
    browser.py                 one Chromium per process, a fresh context per request
    checks.py                  measurements taken in the page (see "Checks")
    config.py                  limits: viewport sizes, timeouts, max bytes, allowed hosts
    schemas.py                 request/response models, shared with the client
  src/render_client/           what the API and worker import
    client.py                  httpx client, timeouts, "unavailable" handling
    ports.py                   RenderFn protocol, so tests use a fake
  Dockerfile                   + a `render` stage: same deps + Playwright Chromium
  docker-compose.yml           + `render` service
```

`render_client` is split from `render` on purpose: the API and worker import the client
only, and `playwright` is never imported where it is not installed.

### Compose

```yaml
  render:
    build:
      context: .
      target: render
    image: ${RENDER_IMAGE}
    restart: unless-stopped
    command: uvicorn src.render.app:app --host 0.0.0.0 --port 8100 --workers 1
    environment:
      RENDER_SHARED_SECRET: ${RENDER_SHARED_SECRET}
    networks: [render]        # reachable by api and worker only
    mem_limit: 1g
    cpus: 1.0
    read_only: true
    tmpfs: [/tmp]
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8100/health').status==200 else 1)"]
```

`api` and `worker` join the `render` network and get `RENDER_URL=http://render:8100` and
the same `RENDER_SHARED_SECRET`. The service gets **none** of `x-app-environment`: no
database URL, no bucket keys, no Fernet key, no signing secret, no provider keys. It takes
HTML in and returns bytes and measurements out.

### Image

A second stage in the existing `Dockerfile`, built from the same `uv.lock` with a
`render` dependency group (`playwright`) and `playwright install --with-deps chromium`.
Expected size: the current image plus 300–400 MB, for this service only. `api`, `worker`
and `migrate` are unchanged.

## Security

The service renders HTML an agent wrote, which may carry text a user pasted. Treat every
page as hostile.

| Layer | Control |
|---|---|
| Secrets | None in the container (above). A compromise reaches a browser and nothing else |
| Caller | `X-Render-Secret` header compared in constant time; not exposed on a host port |
| Network, in code | Playwright `route("**/*")` aborts every request except `data:` and `https://fonts.googleapis.com` / `fonts.gstatic.com` — the same allowlist as `src/exports/config.py`, imported from there. No redirects followed |
| Network, in compose | Own network; outbound limited to the font hosts by an egress rule where the host supports it. In code is the layer we rely on; compose is defence in depth |
| JavaScript | `java_script_enabled=False` on every context |
| Isolation | A new browser context per request (no cookies, storage or cache shared between pages). The browser process restarts after N renders or on any crash |
| Resources | Per-request timeout (30 s); max HTML size (5 MB, images already embedded by `ProjectFiles.embed_images`); max output height (40 000 px, matching `PNG_MAX_HEIGHT_PX`); container memory and CPU caps; one render at a time per worker process, queued |
| Filesystem | Read-only root, `/tmp` as tmpfs, non-root user |
| Chromium sandbox | Kept on. If the host kernel refuses it, run with the seccomp profile Playwright documents — never `--no-sandbox` silently |

## Endpoints

| Endpoint | Input | Output | Used by |
|---|---|---|---|
| `POST /check` | html, viewports (default 375 and 1440) | measurements per viewport + one screenshot per viewport (PNG, capped size) | page builder revision pass |
| `POST /png` | html, width, full_page, scale | PNG bytes, height | `HtmlToPng` |
| `POST /pdf` | html, mode `paged` (A4/Letter) or `scroll` (one page, full height, fixed width) | PDF bytes, pages | `HtmlToPdf` scroll mode; paged stays on WeasyPrint at first |

## Checks

Measured in the page, at each viewport, with a small script run by Playwright from the
outside (`page.evaluate`) — the page's own scripts stay disabled:

1. **Horizontal overflow** — `document.documentElement.scrollWidth > innerWidth`, and the
   elements whose right edge passes the viewport, with a selector path for each.
2. **Dropped CSS** — rules in the page's `<style>` that the browser's CSSOM did not keep
   (declared text vs. parsed `cssRules`), and custom properties used but never defined.
3. **Raw values** — computed `color`/`background-color`/`margin`/`padding` values that do
   not match any `:root` token's computed value (the "every colour is a token" rule,
   measured instead of read).
4. **Small text** — form fields under 16 px; body text under 14 px at 375.
5. **Images** — `<img>` without `width`/`height` attributes; images that failed to load.
6. **Contrast** — text whose computed foreground/background contrast is under 4.5:1.
7. **Fonts** — families requested but not loaded (`document.fonts`), so a missing Google
   Font shows up instead of falling back silently.

Each check returns findings, not a score. The kit's own rule applies: **a gate that only
says green is decoration** — every check gets a test that plants the defect and proves the
check catches it.

## Changes in the existing code

### Page builder (`src/html_pages/`)

- New builder tool `CheckPage(project, path)` in `BUILDER_TOOLS`: reads the page, embeds
  its images, calls `/check`, returns the findings as text.
- `BUILDER_PROMPT` step 2 changes from "look for" to: call `CheckPage`, fix what it found
  with targeted edits, call it again; report findings left unfixed. Max two check rounds,
  inside the existing `BUILDER_MAX_ITERATIONS`.
- If the render service is down, `CheckPage` says so and the builder falls back to today's
  read-through pass. A page is never blocked on the checker.

### Seeing the screenshot (needs core work)

Tool results are text only today: `tool_result(tool_call_id, content: str)` in
`src/core/llm/domain.py`. Images reach a model only as user-message blocks
(`src/conversations/attachments.py`). Two options:

- **A — image tool results.** Let a tool return `[text, image]` and have each provider
  adapter send it the way that provider accepts (Anthropic: image blocks inside the tool
  result; OpenAI chat: a tool message cannot hold an image, so the adapter adds a user
  message with the image right after). Touches the LLM port, both adapters and the
  executor. Reusable by every future tool that produces an image.
- **B — screenshot as a follow-up user message, builder only.** `CheckPage` returns text;
  the builder loop appends a user message with the screenshot after it. Smaller, local to
  `html_pages`, not reusable.

**Recommendation: A.** It is the right seam, and image tools (`GenerateImages`,
`EditImage`, `PdfToImages`) currently cannot show the model their own output either.
Ship the measured checks first (phase 2) and the screenshot second (phase 3), so the
measurable gain does not wait on the core change.

### Exports (`src/exports/`)

- `HtmlToPng` renders through `/png` when the service is up and falls back to WeasyPrint
  when it is not, saying which it used.
- `HtmlToPdf` gains `layout: "paged" | "scroll"`. `paged` stays on WeasyPrint (tuned, fits
  wide content, works today); `scroll` goes to `/pdf`. Revisit moving `paged` to Chromium
  only if a comparison on real pages favours it.

## Phases

| # | Phase | Delivers | Estimate |
|---|---|---|---|
| 1 | Service skeleton | `src/render`, `render_client`, Dockerfile stage, compose service, network lockdown, `/health`, `/png`. Tests: allowlist blocks a non-font request; JS stays off; a page cannot read another's state; timeout kills a runaway page | 1 day |
| 2 | Checks + `CheckPage` | `/check` with checks 1–7, each with a planted-defect test; builder tool and prompt; fallback when the service is down | 1–1.5 days |
| 3 | Image tool results | option A across the LLM port and both adapters; `CheckPage` attaches screenshots | 1 day |
| 4 | Exports | `HtmlToPng` via the service; `HtmlToPdf` scroll mode; side-by-side comparison of 10 real pages (WeasyPrint vs. Chromium) recorded in this doc | 0.5 day |

**Total: about 3.5–4 days.** Phases 1–2 deliver most of the value and can ship alone.

## Decisions needed before starting

1. **Hosting.** Where production runs decides the egress control and whether Chromium's
   sandbox works unmodified. Check before phase 1.
2. **Option A vs. B** for screenshots (recommendation: A).
3. **Image size budget.** Two screenshots per check round, two rounds, is four images in
   the builder's context per page. Each is capped (long side ≤ 1568 px, as for
   attachments), but it is real token cost per page built.

## Measuring that it worked

Before phase 2 ships, build the same 10 briefs with and without `CheckPage` and record:
pages with horizontal overflow at 375 px, raw colour/spacing values, missing image
dimensions, form fields under 16 px, and builder steps used. Ship only if defects drop and
steps stay inside `BUILDER_MAX_ITERATIONS`. Numbers go in this doc, not in a summary.
