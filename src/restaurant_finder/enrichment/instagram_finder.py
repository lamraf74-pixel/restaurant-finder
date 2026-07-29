"""Recherche du profil Instagram officiel d'un restaurant.

Stratégie (heuristique, assumée comme "best effort") :
1. Construire une requête de recherche à partir du nom + de la ville.
2. Interroger un `SearchProvider` (DuckDuckGo par défaut).
3. Ne garder que les résultats pointant vers un profil `instagram.com`
   (en excluant les pages génériques : posts, reels, explore...).
4. Évaluer la similarité entre le nom du restaurant et chaque candidat
   (titre de la page + identifiant du compte) via `matching.score_candidate`.
5. Retenir le meilleur candidat si son score dépasse le seuil configuré.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from urllib.parse import urlparse

from restaurant_finder.cache import FileCache
from restaurant_finder.config import Settings
from restaurant_finder.domain.models import Restaurant
from restaurant_finder.enrichment.matching import score_candidate
from restaurant_finder.enrichment.search_providers.base import SearchProvider
from restaurant_finder.exceptions import SearchProviderError

logger = logging.getLogger(__name__)

_INSTAGRAM_HOST_PATTERN = re.compile(r"(^|\.)instagram\.com$")
_RESERVED_PATH_SEGMENTS = {
    "p",
    "reel",
    "reels",
    "explore",
    "accounts",
    "stories",
    "directory",
    "developer",
    "about",
    "legal",
    "tv",
}
_HANDLE_PATTERN = re.compile(r"^/([A-Za-z0-9_.]+)/?")


class InstagramFinder:
    """Tente de retrouver le profil Instagram officiel d'un restaurant.

    Thread-safe : plusieurs threads peuvent appeler `find()` en parallèle
    (voir `RestaurantFinderService`), le rate limiter interne garantit un
    espacement minimal entre les *départs* de requêtes sans bloquer les
    appels réseau eux-mêmes (ceux-ci peuvent donc se chevaucher).
    """

    def __init__(
        self,
        search_provider: SearchProvider,
        settings: Settings,
        cache: FileCache | None = None,
    ) -> None:
        self._search_provider = search_provider
        self._settings = settings
        self._cache = cache
        self._last_request_time: float = 0.0
        self._rate_limit_lock = threading.Lock()

    def find(self, restaurant: Restaurant) -> str | None:
        """Retourne l'URL Instagram la plus probable, ou None si non trouvée."""

        cache_key = f"instagram:{restaurant.osm_id}:{restaurant.name}:{restaurant.city}"
        if self._cache is not None:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached or None

        result = self._search_instagram(restaurant)

        if self._cache is not None:
            self._cache.set(cache_key, result or "")

        return result

    def _search_instagram(self, restaurant: Restaurant) -> str | None:
        self._respect_rate_limit()

        query = f'"{restaurant.name}" {restaurant.city} instagram'
        try:
            results = self._search_provider.search(
                query, max_results=self._settings.instagram_max_search_results
            )
        except SearchProviderError as exc:
            logger.warning("Recherche Instagram impossible pour %r : %s", restaurant.name, exc)
            return None

        best_handle: str | None = None
        best_score = -1

        for result in results:
            handle = self._extract_handle(result.url)
            if handle is None:
                continue

            candidate_text = f"{result.title} {handle.replace('.', ' ').replace('_', ' ')}"
            score = score_candidate(restaurant.name, candidate_text)

            if score > best_score:
                best_score = score
                best_handle = handle

        if best_handle is None or best_score < self._settings.instagram_match_threshold:
            logger.debug(
                "Aucun profil Instagram fiable pour %r (meilleur score : %d).",
                restaurant.name,
                best_score,
            )
            return None

        logger.debug(
            "Profil Instagram trouvé pour %r : @%s (score %d).",
            restaurant.name,
            best_handle,
            best_score,
        )
        return f"https://www.instagram.com/{best_handle}/"

    def _respect_rate_limit(self) -> None:
        """Espace les départs de requêtes d'au moins `instagram_search_delay_seconds`."""

        with self._rate_limit_lock:
            elapsed = time.monotonic() - self._last_request_time
            wait_time = self._settings.instagram_search_delay_seconds - elapsed
            if wait_time > 0:
                time.sleep(wait_time)
            self._last_request_time = time.monotonic()

    @staticmethod
    def _extract_handle(url: str) -> str | None:
        """Extrait un identifiant de compte Instagram depuis une URL, si valide."""

        parsed = urlparse(url)
        if not _INSTAGRAM_HOST_PATTERN.search(parsed.netloc):
            return None

        match = _HANDLE_PATTERN.match(parsed.path)
        if not match:
            return None

        handle = match.group(1)
        if handle.lower() in _RESERVED_PATH_SEGMENTS:
            return None

        return handle
