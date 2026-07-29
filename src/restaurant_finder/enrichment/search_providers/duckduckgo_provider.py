"""Fournisseur de recherche web basé sur la page HTML publique de DuckDuckGo.

Ne nécessite aucune clé API, ce qui correspond au besoin d'une solution
gratuite. En contrepartie il s'agit de scraping HTML : la page peut
changer de structure sans préavis. Ce risque est volontairement isolé
dans cette unique classe (voir `SearchProvider` pour le contrat abstrait).
"""

from __future__ import annotations

import logging
from urllib.parse import parse_qs, unquote, urlparse

import requests
from bs4 import BeautifulSoup

from restaurant_finder.config import Settings
from restaurant_finder.enrichment.search_providers.base import SearchProvider, SearchResult
from restaurant_finder.exceptions import SearchProviderError

logger = logging.getLogger(__name__)

_SEARCH_URL = "https://html.duckduckgo.com/html/"


class DuckDuckGoSearchProvider(SearchProvider):
    """Recherche web via `html.duckduckgo.com` (pas de clé API requise)."""

    def __init__(self, session: requests.Session, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        try:
            response = self._session.post(
                _SEARCH_URL,
                data={"q": query},
                timeout=self._settings.request_timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise SearchProviderError(
                f"Échec de la recherche DuckDuckGo pour {query!r}: {exc}"
            ) from exc

        soup = BeautifulSoup(response.text, "html.parser")
        results: list[SearchResult] = []

        for result_div in soup.select("div.result"):
            link = result_div.select_one("a.result__a")
            if link is None or not link.get("href"):
                continue

            snippet_tag = result_div.select_one("a.result__snippet, .result__snippet")
            snippet = snippet_tag.get_text(" ", strip=True) if snippet_tag else ""

            resolved_url = self._resolve_url(str(link["href"]))
            results.append(
                SearchResult(
                    title=link.get_text(" ", strip=True),
                    url=resolved_url,
                    snippet=snippet,
                )
            )

            if len(results) >= max_results:
                break

        return results

    @staticmethod
    def _resolve_url(href: str) -> str:
        """DuckDuckGo redirige via `//duckduckgo.com/l/?uddg=<url encodée>`."""

        if "uddg=" not in href:
            return href

        parsed = urlparse(href if href.startswith("http") else f"https:{href}")
        query_params = parse_qs(parsed.query)
        target = query_params.get("uddg")
        return unquote(target[0]) if target else href
