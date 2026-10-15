"""Every check catches the defect planted for it, and a clean page comes back clean. A
gate that only says green is decoration. Needs Chromium; skipped without it."""

import pytest

pytest.importorskip("playwright.async_api")

from src.render import checks
from src.render.browser import Browser


@pytest.fixture
async def browser():
    browser = Browser()
    try:
        await browser.start()
    except Exception as exc:  # noqa: BLE001 -- package installed, browser binary missing
        pytest.skip(f"Chromium is not installed here: {exc}")
    yield browser
    await browser.stop()


CLEAN = """<!doctype html><html lang="es"><head><style>
:root { --ink: #1a1a1a; --ground: #ffffff; --accent: #0052fe; --space-1: 8px; --space-2: 16px; --space-3: 24px; }
body { margin: 0; color: var(--ink); background: var(--ground); font-family: sans-serif; font-size: 16px; }
main { padding: var(--space-3) var(--space-2); max-width: 100%; }
h1 { margin: 0 0 var(--space-2); }
p { margin: 0 0 var(--space-1); }
a { color: var(--accent); }
input { font-size: 16px; padding: var(--space-1); color: var(--ink); background: var(--ground); }
</style></head><body><main>
<h1>Informe</h1><p>Texto claro. <a href="#x">Enlace</a></p>
<img src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7" width="1" height="1" alt="">
<input type="text" value="Nombre" aria-label="Nombre">
</main></body></html>"""


def page(style: str, body: str) -> str:
    return CLEAN.replace("</style>", style + "\n</style>").replace("</main>", body + "</main>")


def of(result, check):
    return [f for f in result["findings"] if f["check"] == check]


async def test_a_clean_page_has_no_findings(browser):
    result = await checks.run(browser, CLEAN)

    assert result["findings"] == []


async def test_content_wider_than_a_phone_is_caught_and_named(browser):
    result = await checks.run(browser, page(".wide { width: 600px; height: 10px; }", '<div class="wide"></div>'))

    found = of(result, "overflow")
    assert found and found[0]["width"] == 375
    assert any("div.wide" in example for example in found[0]["examples"])


async def test_something_cut_off_by_a_clipping_parent_is_not_overflow(browser):
    html = page(".clip { overflow: hidden; } .wide { width: 600px; height: 10px; }", '<div class="clip"><div class="wide"></div></div>')

    assert of(await checks.run(browser, html), "overflow") == []


async def test_a_declaration_the_browser_drops_is_caught(browser):
    result = await checks.run(browser, page("h1 { colr: red; padding: 12pz; }", ""))

    examples = [e for f in of(result, "css") for e in f["examples"]]
    assert "colr: red" in examples
    assert "padding: 12pz" in examples


async def test_a_bad_selector_and_an_undefined_token_are_caught(browser):
    result = await checks.run(browser, page("p:hoverr { color: red; } .x { color: var(--missing); }", ""))

    messages = " ".join(f["message"] + " ".join(f["examples"]) for f in of(result, "css"))
    assert "p:hoverr" in messages
    assert "--missing" in messages


async def test_a_raw_colour_and_an_off_scale_space_are_caught(browser):
    result = await checks.run(browser, page(".raw { background: #ff00aa; padding: 13px; }", '<div class="raw">x</div>'))

    messages = " ".join(f["message"] + " ".join(f["examples"]) for f in of(result, "tokens"))
    assert "rgb(255, 0, 170)" in messages
    assert "13px" in messages


async def test_a_small_form_field_is_caught_on_the_phone(browser):
    result = await checks.run(browser, page(".s { font-size: 13px; }", '<input class="s" type="email">'))

    found = of(result, "small_text")
    assert found and found[0]["width"] == 375 and "16px" in found[0]["message"]


async def test_an_unsized_and_a_broken_image_are_caught(browser):
    html = page("", '<img src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7" alt=""><img src="data:image/png;base64,AAAA" width="5" height="5" alt="">')

    messages = " ".join(f["message"] for f in of(await checks.run(browser, html), "images"))
    assert "without width and height" in messages
    assert "did not load" in messages


async def test_low_contrast_text_is_caught(browser):
    html = page(".pale { color: #cccccc; }", '<p class="pale">Casi invisible</p>')

    found = of(await checks.run(browser, html), "contrast")
    assert found and "Casi invisible" in found[0]["examples"][0]


async def test_a_typeface_never_loaded_is_caught(browser):
    html = page("h1 { font-family: 'Fraunces Imaginary', serif; }", "")

    found = of(await checks.run(browser, html), "fonts")
    assert found and "Fraunces Imaginary" in found[0]["examples"][0]


async def test_a_page_without_tokens_is_told_so(browser):
    html = "<html><body><p style='color:#333'>Hola</p></body></html>"

    found = of(await checks.run(browser, html), "tokens")
    assert found and "no :root tokens" in found[0]["message"]


async def test_a_token_at_partial_opacity_is_still_the_token(browser):
    html = page(".veil { background: color-mix(in srgb, var(--accent) 10%, transparent); }", '<div class="veil">x</div>')

    assert of(await checks.run(browser, html), "tokens") == []


async def test_controls_without_names_and_a_page_without_lang_are_caught(browser):
    html = page(
        "",
        '<img src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7" width="1" height="1">'
        '<input type="email"><button></button><h4>Salto</h4>',
    ).replace('<html lang="es">', "<html>")

    result = await checks.run(browser, html)
    messages = " ".join(f["message"] for f in of(result, "names"))

    assert "no lang" in messages
    assert "without alt" in messages
    assert "form fields with no label" in messages
    assert "buttons and links with no name" in messages
    assert "heading levels skipped" in messages
    assert of(result, "accessibility")[0]["message"].startswith("FAILS the accessibility pass mark")


async def test_a_control_whose_focus_cannot_be_seen_is_caught_by_the_keyboard(browser):
    html = page("a:focus, a:focus-visible { outline: none; }", "")

    result = await checks.run(browser, html)

    assert any("no visible change when reached by Tab" in f["message"] for f in of(result, "keyboard"))
    assert any('a ("Enlace")' in example for f in of(result, "keyboard") for example in f["examples"])


async def test_a_clean_page_passes_the_accessibility_mark(browser):
    result = await checks.run(browser, CLEAN)

    assert of(result, "keyboard") == []
    assert of(result, "accessibility") == []
