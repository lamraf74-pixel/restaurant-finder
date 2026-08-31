"""Tests de l'extraction Instagram depuis le site web d'un établissement."""

from __future__ import annotations

import requests
import responses

from restaurant_finder.enrichment.website_instagram import find_instagram_on_website


@responses.activate
def test_find_instagram_on_website_extracts_from_anchor_link() -> None:
    responses.add(
        responses.GET,
        "https://lepetitbistrot.fr/",
        body=(
            '<html><body><footer>'
            '<a href="https://www.instagram.com/lepetitbistrot_off/">Instagram</a>'
            "</footer></body></html>"
        ),
        status=200,
    )

    result = find_instagram_on_website(
        "https://lepetitbistrot.fr/",
        session=requests.Session(),
        timeout=5.0,
    )

    assert result == "https://www.instagram.com/lepetitbistrot_off/"


@responses.activate
def test_find_instagram_on_website_extracts_from_open_graph_meta() -> None:
    responses.add(
        responses.GET,
        "https://restaurant.example/",
        body=(
            '<html><head>'
            '<meta property="og:url" content="https://www.instagram.com/mon_resto/" />'
            "</head></html>"
        ),
        status=200,
    )

    result = find_instagram_on_website(
        "restaurant.example",
        session=requests.Session(),
        timeout=5.0,
    )

    assert result == "https://www.instagram.com/mon_resto/"


@responses.activate
def test_find_instagram_on_website_returns_none_when_no_link() -> None:
    responses.add(
        responses.GET,
        "https://sans-reseaux.fr/",
        body="<html><body><p>Pas de réseaux sociaux</p></body></html>",
        status=200,
    )

    result = find_instagram_on_website(
        "https://sans-reseaux.fr/",
        session=requests.Session(),
        timeout=5.0,
    )

    assert result is None


@responses.activate
def test_find_instagram_on_website_returns_none_on_http_error() -> None:
    responses.add(
        responses.GET,
        "https://site-down.fr/",
        status=503,
    )

    result = find_instagram_on_website(
        "https://site-down.fr/",
        session=requests.Session(),
        timeout=5.0,
    )

    assert result is None
