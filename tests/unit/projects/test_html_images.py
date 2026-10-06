from uuid import uuid4

import pytest

from src.core.settings import settings
from src.projects import html_images, links

PAGE = "soullens-studios-report/report.html"


def test_finds_img_sources_and_css_urls_once_each():
    html = (
        '<img src="../cat/a.png" alt="x"><img alt="y" src=\'b.jpg\'>'
        '<div style="background: url(c.webp)"></div><img src="../cat/a.png">'
        '<style>.hero { background-image: url("d.png"); }</style>'
    )

    assert html_images.references(html) == ["../cat/a.png", "b.jpg", "c.webp", "d.png"]


def test_data_attributes_are_not_mistaken_for_a_source():
    assert html_images.references('<img data-src="x.png" src="y.png">') == ["y.png"]


def test_only_the_swapped_addresses_change():
    html = '<img class="hero" src="a.png"><img src="https://elsewhere/b.png"><p style="background:url(a.png)">'

    out = html_images.replace(html, {"a.png": "data:image/png;base64,AAA"})

    assert out == (
        '<img class="hero" src="data:image/png;base64,AAA"><img src="https://elsewhere/b.png">'
        '<p style="background:url("data:image/png;base64,AAA")">'
    )


@pytest.mark.parametrize(
    ("address", "expected"),
    [
        ("../cat-mouse-merida/cat.png", "cat-mouse-merida/cat.png"),
        ("img/logo.png", "soullens-studios-report/img/logo.png"),
        ("./logo.png?v=2#top", "soullens-studios-report/logo.png"),
        ("/fotos/gato%20negro.png", "fotos/gato negro.png"),
        ("../../outside.png", None),
        ("https://example.com/a.png", None),
        ("data:image/png;base64,AAA", None),
        ("//cdn.example.com/a.png", None),
        ("#section", None),
    ],
)
def test_where_an_address_points_in_the_project(address, expected):
    assert html_images.project_path(PAGE, address) == expected


def test_a_link_is_for_its_file_only(monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_API_URL", "https://api.example.com/")
    file_id = uuid4()

    url = links.view_url(file_id)

    assert url == f"https://api.example.com/api/v1/files/{file_id}/view?sig={links.sign(file_id)}"
    assert links.parse(url) == file_id
    assert links.parse(url.replace(str(file_id), str(uuid4()))) is None
    assert links.parse(url[:-1] + ("0" if url[-1] != "0" else "1")) is None


def test_a_link_still_reads_after_the_api_moves(monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_API_URL", "http://localhost:8000")
    file_id = uuid4()
    url = links.view_url(file_id)

    monkeypatch.setattr(settings, "PUBLIC_API_URL", "https://api.example.com")

    assert links.parse(url) == file_id


def test_no_link_without_a_public_address(monkeypatch):
    monkeypatch.setattr(settings, "PUBLIC_API_URL", None)

    assert links.view_url(uuid4()) is None


def test_the_link_secret_signs_when_set(monkeypatch):
    file_id = uuid4()
    monkeypatch.setattr(settings, "FILE_LINK_SECRET", None)
    default = links.sign(file_id)
    monkeypatch.setattr(settings, "FILE_LINK_SECRET", "another-secret")

    assert links.sign(file_id) != default
