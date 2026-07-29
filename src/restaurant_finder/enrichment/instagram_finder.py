"""Recherche du profil Instagram officiel d'un restaurant.

Priorité :
1. Si OpenStreetMap fournit déjà un tag Instagram → on l'utilise tel quel.
2. Sinon, recherche web (DuckDuckGo) avec plusieurs requêtes successives.
3. Matching flou (rapidfuzz) pour retenir le profil le plus crédible.
"""

from __future__ import annotations

import logging
import threading
import time

from restaurant_finder.cache import FileCache
from restaurant_finder.config import Settings
from restaurant_finder.domain.models import Restaurant
from restaurant_finder.enrichment.instagram_normalize import extract_handle, to_profile_url
from restaurant_finder.enrichment.matching import score_candidate
from restaurant_finder.enrichment.search_providers.base import SearchProvider, SearchResult
from restaurant_finder.exceptions import SearchProviderError

logger = logging.getLogger(__name__)


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

        # Déjà fourni par OSM (contact:instagram) : pas besoin de chercher.
        if restaurant.instagram_url:
            return to_profile_url(restaurant.instagram_url) or restaurant.instagram_url

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
        best_handle: str | None = None
        best_score = -1

        for query in self._build_queries(restaurant):
            self._respect_rate_limit()
            try:
                results = self._search_provider.search(
                    query, max_results=self._settings.instagram_max_search_results
                )
            except SearchProviderError as exc:
                logger.warning(
                    "Recherche Instagram impossible pour %r (%r) : %s",
                    restaurant.name,
                    query,
                    exc,
                )
                continue

            handle, score = self._best_candidate(restaurant, results)
            if handle is not None and score > best_score:
                best_handle = handle
                best_score = score

            # Dès qu'un profil dépasse le seuil, on arrête (objectif = Instagram).
            if best_handle is not None and best_score >= self._settings.instagram_match_threshold:
                break

        if best_handle is None or best_score < self._settings.instagram_match_threshold:
            logger.debug(
                "Aucun profil Instagram fiable pour %r (meilleur score : %d).",
                restaurant.name,
                best_score,
            )
            return None

        logger.info(
            "Instagram trouvé pour %r : @%s (score %d).",
            restaurant.name,
            best_handle,
            best_score,
        )
        return to_profile_url(best_handle)

    @staticmethod
    def _build_queries(restaurant: Restaurant) -> list[str]:
        """Plusieurs formulations pour maximiser le taux de trouvaille Instagram."""

        name = restaurant.name.strip()
        city = restaurant.city.strip()
        return [
            # La plus efficace pour remonter des profils Instagram.
            f'site:instagram.com "{name}" {city}',
            f'"{name}" {city} Instagram',
            f"{name} {city} restaurant Instagram",
        ]

    def _best_candidate(
        self, restaurant: Restaurant, results: list[SearchResult]
    ) -> tuple[str | None, int]:
        best_handle: str | None = None
        best_score = -1

        for result in results:
            handle = extract_handle(result.url)
            if handle is None:
                continue

            candidate_text = (
                f"{result.title} {result.snippet} "
                f"{handle.replace('.', ' ').replace('_', ' ')}"
            )
            score = score_candidate(restaurant.name, candidate_text)

            # Bonus si le handle contient le nom de la ville (ex: lesafari_nice).
            city_token = restaurant.city.strip().lower().replace(" ", "")
            if city_token and city_token in handle.lower().replace("_", "").replace(".", ""):
                score = min(100, score + 8)

            if score > best_score:
                best_score = score
                best_handle = handle

        return best_handle, best_score

    def _respect_rate_limit(self) -> None:
        """Espace les départs de requêtes d'au moins `instagram_search_delay_seconds`."""

        with self._rate_limit_lock:
            elapsed = time.monotonic() - self._last_request_time
            wait_time = self._settings.instagram_search_delay_seconds - elapsed
            if wait_time > 0:
                time.sleep(wait_time)
            self._last_request_time = time.monotonic()
