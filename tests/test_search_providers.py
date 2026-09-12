"""Tests des fournisseurs de recherche web (ddgs, DuckDuckGo HTML) : retry & erreurs."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import requests
import responses

from restaurant_finder.config import Settings
from restaurant_finder.enrichment.search_providers.ddgs_provider import DdgsSearchProvider
from restaurant_finder.enrichment.search_providers.duckduckgo_provider import (
    DuckDuckGoSearchProvider,
)
from restaurant_finder.exceptions import SearchProviderError


class _FakeDDGS:
    """Remplace `ddgs.DDGS` : un compteur d'appels contrôle le comportement."""

    calls = 0
    fail_times = 0
    results: list[dict] = []

    def __enter__(self) -> _FakeDDGS:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def text(self, query: str, max_results: int) -> list[dict]:
        type(self).calls += 1
        if type(self).calls <= type(self).fail_times:
            raise RuntimeError("ddgs indisponible")
        return type(self).results


def _reset_fake_ddgs(fail_times: int, results: list[dict]) -> None:
    _FakeDDGS.calls = 0
    _FakeDDGS.fail_times = fail_times
    _FakeDDGS.results = results


def test_ddgs_provider_retries_then_succeeds() -> None:
    _reset_fake_ddgs(
        fail_times=1,
        results=[{"href": "https://www.instagram.com/lepetitbistrot/", "title": "IG"}],
    )
    settings = Settings(retry_base_delay_seconds=0, retry_max_attempts=3)
    provider = DdgsSearchProvider(settings=settings)

    with patch(
        "restaurant_finder.enrichment.search_providers.ddgs_provider.DDGS", _FakeDDGS
    ):
        results = provider.search("le petit bistrot instagram", max_results=5)

    assert len(results) == 1
    assert results[0].url == "https://www.instagram.com/lepetitbistrot/"
    assert _FakeDDGS.calls == 2


def test_ddgs_provider_raises_search_provider_error_after_persistent_failures() -> None:
    _reset_fake_ddgs(fail_times=5, results=[])
    settings = Settings(retry_base_delay_seconds=0, retry_max_attempts=2)
    provider = DdgsSearchProvider(settings=settings)

    with (
        patch("restaurant_finder.enrichment.search_providers.ddgs_provider.DDGS", _FakeDDGS),
        pytest.raises(SearchProviderError),
    ):
        provider.search("introuvable", max_results=5)

    assert _FakeDDGS.calls == 2


@responses.activate
def test_duckduckgo_provider_retries_on_transient_connection_error() -> None:
    settings = Settings(retry_base_delay_seconds=0, retry_max_attempts=2)
    responses.add(
        responses.POST,
        "https://html.duckduckgo.com/html/",
        body=requests.exceptions.ConnectionError(),
    )
    responses.add(
        responses.POST,
        "https://html.duckduckgo.com/html/",
        body=(
            '<div class="result"><a class="result__a" '
            'href="https://www.instagram.com/lepetitbistrot/">Le Petit Bistrot</a>'
            '<a class="result__snippet">Restaurant à Lyon</a></div>'
        ),
        status=200,
    )

    provider = DuckDuckGoSearchProvider(session=requests.Session(), settings=settings)
    results = provider.search("le petit bistrot", max_results=5)

    assert len(results) == 1
    assert results[0].url == "https://www.instagram.com/lepetitbistrot/"
    assert len(responses.calls) == 2


@responses.activate
def test_duckduckgo_provider_raises_after_persistent_connection_errors() -> None:
    settings = Settings(retry_base_delay_seconds=0, retry_max_attempts=2)
    for _ in range(2):
        responses.add(
            responses.POST,
            "https://html.duckduckgo.com/html/",
            body=requests.exceptions.ConnectionError(),
        )

    provider = DuckDuckGoSearchProvider(session=requests.Session(), settings=settings)

    with pytest.raises(SearchProviderError):
        provider.search("introuvable", max_results=5)

    assert len(responses.calls) == 2
