from src.html_pages import brand

# Shaped like the kit's packs: provenance comments, a role alias in a second :root block,
# and --ink meaning the dark ground rather than text.
TOKENS_CSS = """/* SLS · design tokens */
:root {
  --brand: #0052FE;  /* sealed rectora */
  --brand-dim: rgba(0,82,254,.07);  /* sealed rectora */
  --family-tech: 'Orbitron', 'Mada', ui-sans-serif, sans-serif;  /* sealed rectora */
  --fg: #0A0E1A;  /* sealed rectora */
  --fg-2: #39425E;
  --fg-3: #5D647B;
  --fg-inv: #FFFFFF;
  --ink: #0A0E1A;
  --line: #E3E8F3;
  --paper: #FFFFFF;
  --r: 14px;  /* built site */
  --surface: #F4F6FB;
}

/* engine contract */
:root {
  --font-dsp: var(--family-tech);
}
"""


def test_tokens_are_read_without_their_comments_and_aliases_resolved():
    tokens = brand.parse_tokens(TOKENS_CSS)

    assert tokens["--brand"] == "#0052FE"
    assert tokens["--r"] == "14px"
    assert tokens["--font-dsp"] == "'Orbitron', 'Mada', ui-sans-serif, sans-serif"


def test_a_reference_to_a_missing_token_falls_back_to_its_default():
    tokens = brand.parse_tokens(":root { --a: var(--nope, #123456); }")

    assert tokens["--a"] == "#123456"


def test_pack_names_map_onto_house_roles():
    lines, missing = brand.house_tokens(brand.parse_tokens(TOKENS_CSS))

    assert "  --ground: #FFFFFF;" in lines
    assert "  --ink: #0A0E1A;" in lines
    assert "  --accent: #0052FE;" in lines
    assert "  --accent-soft: rgba(0,82,254,.07);" in lines
    assert missing == []


def test_the_packs_ink_is_never_taken_for_text():
    tokens = brand.parse_tokens(":root { --ink: #111111; --paper: #fff; }")

    lines, missing = brand.house_tokens(tokens)

    assert not any(line.startswith("  --ink:") for line in lines)
    assert "--ink" in missing


def test_a_role_the_pack_lacks_is_named_not_invented():
    section = brand.render("SLS", "Biblioteca", TOKENS_CSS, None, None, [])

    assert "- Body: not in the pack -- use the house default" in section
    assert "- Headings: 'Orbitron'" in section


def test_the_dark_band_uses_the_packs_ink_as_ground():
    section = brand.render("SLS", "Biblioteca", TOKENS_CSS, None, None, [])

    assert "- Dark band ground: #0A0E1A" in section
    assert "- Text on the dark band: #FFFFFF" in section


def test_logos_are_offered_by_their_library_path():
    section = brand.render("SLS", "Biblioteca", TOKENS_CSS, None, None, ["SLS/logo/logo.webp"])

    assert "- project:Biblioteca/SLS/logo/logo.webp" in section
    assert "never redraw it" in section


def test_without_a_logo_the_page_is_told_not_to_draw_one():
    section = brand.render("XST", "Biblioteca", TOKENS_CSS, None, None, [])

    assert "has no logo file. Do not draw one" in section


def test_identity_and_voice_travel_with_the_pack():
    section = brand.render("SLS", "Biblioteca", TOKENS_CSS, "# Identity", "Never say 'synergy'.", [])

    assert "--- identity.md ---\n# Identity" in section
    assert "Never say 'synergy'." in section


def test_a_long_identity_is_cut_and_says_so():
    section = brand.render("SLS", "Biblioteca", TOKENS_CSS, "x" * 20_000, None, [])

    assert "[... cut here; the rest is in the pack]" in section
