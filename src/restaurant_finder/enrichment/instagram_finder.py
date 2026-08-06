"""Recherche du profil Instagram officiel d'un restaurant.

Pipeline en deux temps, pensé pour limiter les faux positifs :

1. **Présélection** : recherche web (ddgs), extraction des handles Instagram
   candidats, score de similarité texte (titre/extrait) pour les classer.
2. **Vérification** : pour les meilleurs candidats, on lit leur vraie page
   de profil (nom complet + biographie), un signal bien plus fiable qu'un
   extrait de résultat de recherche souvent tronqué ou publicitaire, et on
   ne retient le candidat que si ce second score dépasse le seuil.

Si Instagram est temporairement inaccessible pour tous les candidats
testés (page bloquée), on retombe sur le score texte seul avec un seuil
plus strict, plutôt que d'abandonner complètement la recherche.
"""

from __future__ import annotations

import logging
import threading
import time

from restaurant_finder.cache import FileCache
from restaurant_finder.config import Settings
from restaurant_finder.domain.models import Restaurant
from restaurant_finder.enrichment.instagram_normalize import extract_handle, to_profile_url
from restaurant_finder.enrichment.instagram_profile import InstagramProfile, InstagramProfileClient
from restaurant_finder.enrichment.matching import score_candidate
from restaurant_finder.enrichment.search_providers.base import SearchProvider, SearchResult
from restaurant_finder.exceptions import SearchProviderError
from restaurant_finder.utils.text import normalize_text

logger = logging.getLogger(__name__)

#: Score texte minimal en dessous duquel un candidat n'est même pas vérifié
#: (évite de gaspiller une requête réseau sur un résultat déjà clairement hors sujet).
_MIN_SHORTLIST_SCORE = 30
#: Score jugé déjà si convaincant qu'inutile de lancer d'autres requêtes de recherche.
_EARLY_STOP_SCORE = 90


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
        profile_client: InstagramProfileClient | None = None,
        cache: FileCache | None = None,
    ) -> None:
        self._search_provider = search_provider
        self._settings = settings
        self._profile_client = profile_client
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
        candidates: dict[str, int] = {}

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

            for handle, score in self._extract_candidates(restaurant, results):
                if score > candidates.get(handle, -1):
                    candidates[handle] = score

            best_so_far = max(candidates.values(), default=-1)
            if best_so_far >= _EARLY_STOP_SCORE:
                break

        if not candidates:
            logger.debug("Aucun candidat Instagram trouvé pour %r.", restaurant.name)
            return None

        ranked = sorted(candidates.items(), key=lambda item: item[1], reverse=True)
        return self._select_best(restaurant, ranked)

    @staticmethod
    def _build_queries(restaurant: Restaurant) -> list[str]:
        """Requêtes ciblées : moins de requêtes bruitées = moins de faux positifs."""

        name = restaurant.name.strip()
        city = restaurant.city.strip()
        return [
            # La plus précise : cible directement les profils Instagram.
            f'site:instagram.com "{name}" {city}',
            f'"{name}" {city} restaurant Instagram',
        ]

    def _extract_candidates(
        self, restaurant: Restaurant, results: list[SearchResult]
    ) -> list[tuple[str, int]]:
        candidates: list[tuple[str, int]] = []

        for result in results:
            handle = extract_handle(result.url)
            if handle is None:
                continue

            candidate_text = (
                f"{result.title} {result.snippet} "
                f"{handle.replace('.', ' ').replace('_', ' ')}"
            )
            score = score_candidate(restaurant.name, candidate_text)
            score, _ = self._apply_city_bonus(restaurant, handle, score)
            candidates.append((handle, score))

        return candidates

    def _select_best(
        self, restaurant: Restaurant, ranked: list[tuple[str, int]]
    ) -> str | None:
        if self._profile_client is None:
            return self._best_by_text_only(ranked, self._settings.instagram_match_threshold)

        checked = 0
        fetch_failures = 0

        for handle, prelim_score in ranked:
            if prelim_score < _MIN_SHORTLIST_SCORE:
                break  # trié par score décroissant : le reste sera pire.
            if checked >= self._settings.instagram_max_profile_checks:
                break
            checked += 1

            profile = self._profile_client.get_profile(handle)
            if profile is None:
                fetch_failures += 1
                continue

            verified_score = self._verify_profile(restaurant, handle, profile)
            if verified_score >= self._settings.instagram_match_threshold:
                logger.info(
                    "Instagram vérifié pour %r : @%s (score %d, %s follower(s)).",
                    restaurant.name,
                    handle,
                    verified_score,
                    profile.follower_count,
                )
                return to_profile_url(handle)

            logger.debug(
                "Candidat @%s écarté pour %r (score profil %d < seuil).",
                handle,
                restaurant.name,
                verified_score,
            )

        if checked > 0 and fetch_failures == checked:
            # Instagram inaccessible pour tous les candidats testés (bloqué,
            # hors ligne...) : on retombe sur le score texte seul, avec une
            # barre plus haute par prudence plutôt que d'abandonner.
            fallback_threshold = max(self._settings.instagram_match_threshold, 75)
            logger.debug(
                "Profils Instagram illisibles pour %r : repli sur le score texte (seuil %d).",
                restaurant.name,
                fallback_threshold,
            )
            return self._best_by_text_only(ranked, fallback_threshold)

        logger.debug("Aucun profil Instagram vérifié pour %r.", restaurant.name)
        return None

    @staticmethod
    def _best_by_text_only(ranked: list[tuple[str, int]], threshold: int) -> str | None:
        if not ranked:
            return None
        handle, score = ranked[0]
        if score < threshold:
            return None
        return to_profile_url(handle)

    def _verify_profile(
        self, restaurant: Restaurant, handle: str, profile: InstagramProfile
    ) -> int:
        """Score de confiance basé sur les vraies données du profil (pas un extrait web)."""

        handle_readable = handle.replace(".", " ").replace("_", " ")
        identity_text = f"{profile.full_name} {handle_readable}".strip()
        score = score_candidate(restaurant.name, identity_text) if identity_text else 0

        normalized_name = normalize_text(restaurant.name)
        normalized_bio = normalize_text(profile.biography)
        if normalized_name and normalized_name in normalized_bio:
            # Le nom exact du restaurant apparaît dans la bio : signal quasi
            # certain, qui ne doit pas être noyé par un score textuel de base
            # faible (ex: nom complet du compte très différent du nom affiché).
            score = max(score, 85)

        score, city_confirmed = self._apply_city_bonus(
            restaurant, handle, score, biography=profile.biography
        )

        if not city_confirmed and score < 95:
            # Sans confirmation de ville (ni dans le handle, ni dans la bio),
            # deux établissements au nom quasi identique mais dans des villes
            # différentes (enseignes régionales, ex: "Le Castello" à Nice vs
            # "Il Castello" à Brest) sont une source fréquente de faux
            # positifs : on exige une marge de sécurité supplémentaire.
            score = max(0, score - self._settings.instagram_unconfirmed_city_penalty)

        return score

    @staticmethod
    def _apply_city_bonus(
        restaurant: Restaurant, handle: str, score: int, biography: str = ""
    ) -> tuple[int, bool]:
        """Bonus si la ville apparaît dans le handle ou la biographie (ex: lesafari_nice).

        Retourne aussi si la ville a pu être confirmée (utilisé pour exiger
        une marge de sécurité supplémentaire quand ce n'est pas le cas).
        """

        city_token = restaurant.city.strip().lower().replace(" ", "")
        if not city_token:
            return score, True  # pas de ville connue : rien à confirmer.

        normalized_handle = handle.lower().replace("_", "").replace(".", "")
        if city_token in normalized_handle:
            return min(100, score + 8), True

        if biography and city_token in normalize_text(biography).replace(" ", ""):
            return min(100, score + 5), True

        return score, False

    def _respect_rate_limit(self) -> None:
        """Espace les départs de requêtes d'au moins `instagram_search_delay_seconds`."""

        with self._rate_limit_lock:
            elapsed = time.monotonic() - self._last_request_time
            wait_time = self._settings.instagram_search_delay_seconds - elapsed
            if wait_time > 0:
                time.sleep(wait_time)
            self._last_request_time = time.monotonic()
