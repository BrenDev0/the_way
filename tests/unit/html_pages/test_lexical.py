from src.html_pages import lexical

# Shaped like the kit's packs: the forbidden words written as prose, a sentence around them.
SLS_VOICE = """# Soul Lens Studios — Voice

## Vocabulary

Avoid generic words like "creativity" or "marketing".

## Words that never appear

Cotización / cotizador / propuesta (say Plan Maestro instead); GHL or "Go High Level" (say CX instead); "newsletter"; "gratis" (the brand demonstrates value); and any war language — enemigo, batalla, conquistar. Placeholder markers such as TODO, LOREM IPSUM, or FIXME must never reach a published page. No emoji, ever. (qa-lexico.mjs)

The word "garantía" is conditional, not simply banned or allowed: it may only be published when sealed.

## How it sounds

Premium and direct.
"""

XST_VOICE = """## Prohibited words
- "cotización" / "cotizador" (quote / quoting tool) — the commercial document is a Plan Maestro (qa-lexico.mjs)
- "Cloudflare" in customer-facing copy — say "a global network of 300+ cities" instead (qa-lexico.mjs)
- Unresolved template placeholders ("{{ }}") or open task markers ("TODO") in anything shipped
"""


def test_the_forbidden_words_are_read_out_of_the_prose():
    terms = lexical.forbidden_terms(SLS_VOICE)

    for word in ("Cotización", "cotizador", "propuesta", "GHL", "Go High Level", "newsletter", "gratis",
                 "enemigo", "batalla", "conquistar", "TODO", "LOREM IPSUM", "FIXME", "garantía"):
        assert word in terms
    # the sentence around the list is not the list
    for phrase in ("ever", "allowed", "creativity", "Plan Maestro", "CX"):
        assert phrase not in terms


def test_the_word_to_use_instead_is_not_forbidden():
    terms = lexical.forbidden_terms(XST_VOICE)

    assert {"cotización", "cotizador", "Cloudflare", "{{ }}", "TODO"} <= set(terms)
    assert "a global network of 300+ cities" not in terms


def test_a_pack_with_nothing_sealed_forbids_nothing():
    assert lexical.forbidden_terms("## Forbidden words\nN/A — not sealed yet.") == []
    assert lexical.forbidden_terms(None) == []


def test_only_what_a_visitor_reads_is_searched():
    raw = (
        '<html><head><style>.gratis{}</style><meta name="description" content="Plan sin costo"></head>'
        '<body><!-- gratis --><p>Tu Plan Maestro</p><img alt="Equipo SLS" src="x.png">'
        "<script>var gratis = 1</script></body></html>"
    )

    text = lexical.visible_text(raw)

    assert "Tu Plan Maestro" in text and "Equipo SLS" in text and "Plan sin costo" in text
    assert "gratis" not in text


def test_a_forbidden_word_is_found_whole_and_in_any_case():
    found = lexical.occurrences("Cotiza ya. Pide tu COTIZACIÓN hoy, {{ }} pendiente", ["cotización", "{{ }}", "cotiza"])

    assert set(found) == {"cotización", "{{ }}", "cotiza"}
    assert "COTIZACIÓN" in found["cotización"]
    assert lexical.occurrences("cotizaciones", ["cotización"]) == {}


def test_notes_in_comments_are_caught_but_browser_directives_are_not():
    raw = "<!-- TODO: confirm price with Ana --><p>x</p><!--[if IE]><p>old</p><![endif]--><!---->"

    assert lexical.comments(raw) == ["TODO: confirm price with Ana"]


def test_another_brands_traces_are_named():
    others = [
        lexical.OtherBrand(
            folder="GRE",
            names=lexical.brand_names("GRE", "# GRE (Gin Real Estate) — Identity\n\ntext"),
            colours=lexical.accent_colours(":root { --brand: #c8a24b; --brand-lift: #d4b46a; }"),
        )
    ]
    raw = (
        '<style>.cta{background:#C8A24B}</style><p>Desarrollado por Gin Real Estate</p>'
        '<img src="project:Biblioteca/GRE/logo/logo.png">'
    )

    traces = lexical.other_brand_traces(raw, lexical.visible_text(raw), "Biblioteca", {"#0052FE"}, others)

    assert "the name 'Gin Real Estate' (GRE) appears in the copy" in traces
    assert "it uses files from GRE's library folder" in traces
    assert "GRE's signature colour #C8A24B is in the page" in traces


def test_a_brand_code_inside_an_ordinary_word_is_not_a_trace():
    others = [lexical.OtherBrand(folder="EXA", names=("EXA",))]

    assert lexical.other_brand_traces("<p>exacto, exa</p>", "exacto, exa", "Biblioteca", set(), others) == []
