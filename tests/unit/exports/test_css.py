from src.exports.css import print_safe


def css_of(html: str) -> str:
    return print_safe(html, screen_width=1440, screen_height=900)


def test_a_screen_height_section_grows_with_its_content_instead_of_clipping():
    out = css_of("<style>.hero { height: 100vh; overflow: hidden } .cover { min-height: 50vh }</style>")

    assert ".hero { min-height: 900px;" in out
    assert ".cover { min-height: 450px }" in out


def test_viewport_widths_and_the_new_viewport_units_become_pixels():
    out = css_of("<style>.band { width: 100vw; padding: 2vmin 5dvw } .x { max-height: 80svh }</style>")

    assert "width: 1440px" in out
    assert "padding: 18px 72px" in out
    assert "max-height: none" in out


def test_line_height_and_min_height_are_not_mistaken_for_height():
    out = css_of("<style>p { line-height: 1.5 } .a { min-height: 10vh }</style>")

    assert "line-height: 1.5" in out
    assert "min-height: 90px" in out


def test_fixed_is_placed_once_and_sticky_stays_where_it_is():
    out = css_of("<style>nav { position: fixed } th { position: sticky }</style>")

    assert "nav { position: absolute }" in out
    assert "th { position: relative }" in out


def test_inline_styles_are_fixed_too_but_the_text_never_is():
    out = css_of('<div style="height: 100vh">The 100vh hero, position: fixed</div>')

    assert 'style="min-height: 900px"' in out
    assert "The 100vh hero, position: fixed" in out
