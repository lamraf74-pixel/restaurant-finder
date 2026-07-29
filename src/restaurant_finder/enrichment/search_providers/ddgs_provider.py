"""Fournisseur de recherche web basé sur la librairie `ddgs` (ex duckduckgo-search).

Contrairement au scraping HTML direct de DuckDuckGo (souvent bloqué par
anti-bot HTTP 202), `ddgs` agrège plusieurs backends de recherche et
reste utilisable sans clé API — adapté à la découverte de profils
Instagram.
"""

from __future__ import annotations

import logging
import threading

from ddgs import DDGS

from restaurant_finder.config import Settings
from restaurant_finder.enrichment.search_providers.base import SearchProvider, SearchResult
from restaurant_finder.exceptions import SearchProviderError

logger = logging.getLogger(__name__)


class DdgsSearchProvider(SearchProvider):
    """Recherche web via la librairie `ddgs` (sans clé API)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = threading.Lock()

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        try:
            # Un seul appel réseau à la fois : les backends publics sont sensibles
            # au parallélisme agressif et peuvent renvoyer des pages vides.
            with self._lock, DDGS() as client:
                raw_results = list(client.text(query, max_results=max_results))
        except Exception as exc:  # noqa: BLE001 - API tierce hétérogène
            raise SearchProviderError(
                f"Échec de la recherche ddgs pour {query!r}: {exc}"
            ) from exc

        results: list[SearchResult] = []
        for item in raw_results:
            url = str(item.get("href") or item.get("link") or "").strip()
            title = str(item.get("title") or "").strip()
            snippet = str(item.get("body") or item.get("description") or "").strip()
            if not url:
                continue
            results.append(SearchResult(title=title, url=url, snippet=snippet))

        if not results:
            logger.debug("ddgs : aucun résultat pour %r.", query)

        return results
