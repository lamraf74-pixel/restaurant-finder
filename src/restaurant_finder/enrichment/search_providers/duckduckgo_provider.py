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
from restaurant_finder.utils.retry import call_with_retry

logger = logging.getLogger(__name__)

_TRANSIENT_NETWORK_ERRORS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)

_SEARCH_URL = "https://html.duckduckgo.com/html/"

# DuckDuckGo refuse souvent les User-Agent "bot" et renvoie alors 0 résultat.
# Un UA navigateur réaliste est requis pour obtenir des résultats exploitables.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://html.duckduckgo.com/",
}


class DuckDuckGoSearchProvider(SearchProvider):
    """Recherche web via `html.duckduckgo.com` (pas de clé API requise)."""

    def __init__(self, session: requests.Session, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        try:
            response = call_with_retry(
                lambda: self._session.post(
                    _SEARCH_URL,
                    data={"q": query},
                    headers=_BROWSER_HEADERS,
                    timeout=self._settings.request_timeout_seconds,
                ),
                operation=f"Recherche DuckDuckGo {query!r}",
                attempts=self._settings.retry_max_attempts,
                base_delay=self._settings.retry_base_delay_seconds,
                backoff_factor=self._settings.retry_backoff_factor,
                retry_on=_TRANSIENT_NETWORK_ERRORS,
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

        if not results:
            logger.debug("DuckDuckGo : aucun résultat pour %r.", query)

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
