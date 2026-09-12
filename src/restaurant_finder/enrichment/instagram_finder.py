"""Recherche du profil Instagram officiel d'un restaurant.

Pipeline en deux temps, pensé pour limiter les faux positifs :

1. **Présélection** : recherche web (ddgs), extraction des handles Instagram
   candidats, score de similarité texte (titre/extrait) pour les classer.
2. **Vérification** : pour les meilleurs candidats, on lit leur vraie page
   de profil (nom complet + biographie), un signal bien plus fiable qu'un
   extrait de résultat de recherche souvent tronqué ou publicitaire, et on
   ne retient le candidat que si ce second score dépasse le seuil.

Chaque association retenue porte un niveau de confiance explicite
(Élevé / Moyen / Faible) basé sur la présence littérale du nom et de la
ville dans le profil — distinct du score rapidfuzz numérique.

Si Instagram est temporairement inaccessible pour tous les candidats
testés (page bloquée), on retombe sur le score texte seul avec un seuil
plus strict, plutôt que d'abandonner complètement la recherche.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import NamedTuple

import requests

from restaurant_finder.cache import FileCache
from restaurant_finder.config import Settings
from restaurant_finder.domain.models import InstagramConfidence, Restaurant
from restaurant_finder.enrichment.confidence import classify_instagram_confidence
from restaurant_finder.enrichment.instagram_normalize import (
    extract_handle,
    extract_handles_from_text,
    to_profile_url,
)
from restaurant_finder.enrichment.instagram_profile import InstagramProfile, InstagramProfileClient
from restaurant_finder.enrichment.matching import score_candidate
from restaurant_finder.enrichment.search_providers.base import SearchProvider, SearchResult
from restaurant_finder.enrichment.website_instagram import find_instagram_on_website
from restaurant_finder.exceptions import SearchProviderError
from restaurant_finder.utils.text import normalize_text

logger = logging.getLogger(__name__)

#: Score texte minimal en dessous duquel un candidat n'est même pas vérifié
#: (évite de gaspiller une requête réseau sur un résultat déjà clairement hors sujet).
_MIN_SHORTLIST_SCORE = 30
#: Score minimal pour conserver un candidat non vérifié en confiance Faible
#: (revue manuelle). En dessous : trop faible pour même figurer dans a_verifier.
_MIN_UNCERTAIN_SCORE = 50


class InstagramMatch(NamedTuple):
    """Association restaurant ↔ Instagram, avec son niveau de confiance."""

    url: str
    confidence: InstagramConfidence


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
        http_session: requests.Session | None = None,
    ) -> None:
        self._search_provider = search_provider
        self._settings = settings
        self._profile_client = profile_client
        self._cache = cache
        self._http_session = http_session
        self._last_request_time: float = 0.0
        self._rate_limit_lock = threading.Lock()

    def find(self, restaurant: Restaurant) -> InstagramMatch | None:
        """Retourne le meilleur match Instagram, ou None si rien de plausible."""

        # (1) Tag OSM contact:instagram — source fiable, confiance Élevé forcée.
        if restaurant.instagram_url:
            url = to_profile_url(restaurant.instagram_url) or restaurant.instagram_url
            return self._match_from_trusted_source(url)

        # (2) Scraping du site web OSM si aucun Instagram trouvé à l'étape 1.
        website_match = self._find_on_website(restaurant)
        if website_match is not None:
            return website_match

        cache_key = f"instagram:{restaurant.osm_id}:{restaurant.name}:{restaurant.city}"
        if self._cache is not None:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return self._match_from_cache(restaurant, cached)

        # (3) Cascade DuckDuckGo en dernier recours.
        result = self._search_instagram(restaurant)

        if self._cache is not None:
            if result is None:
                self._cache.set(cache_key, "")
            else:
                self._cache.set(
                    cache_key,
                    {"url": result.url, "confidence": result.confidence.value},
                )

        return result

    def _find_on_website(self, restaurant: Restaurant) -> InstagramMatch | None:
        website = (restaurant.website or "").strip()
        if not website or self._http_session is None:
            return None

        profile_url = find_instagram_on_website(
            website,
            session=self._http_session,
            timeout=self._settings.instagram_website_timeout_seconds,
            retry_attempts=self._settings.retry_max_attempts,
            retry_base_delay=self._settings.retry_base_delay_seconds,
            retry_backoff_factor=self._settings.retry_backoff_factor,
        )
        if profile_url is None:
            return None

        logger.info(
            "Instagram trouvé sur le site web de %r : %s",
            restaurant.name,
            profile_url,
        )
        return self._match_from_trusted_source(profile_url)

    def _match_from_trusted_source(self, url: str) -> InstagramMatch:
        """Source directe (OSM ou site web) : confiance Élevé sans scoring."""

        return InstagramMatch(url=url, confidence=InstagramConfidence.ELEVE)

    def _match_from_cache(
        self, restaurant: Restaurant, cached: object
    ) -> InstagramMatch | None:
        if not cached:
            return None
        if isinstance(cached, str):
            # Ancien format cache : URL seule → on reclasse à la volée.
            return self._match_from_known_url(restaurant, cached)
        if isinstance(cached, dict):
            url = str(cached.get("url") or "")
            if not url:
                return None
            raw_confidence = cached.get("confidence")
            try:
                confidence = InstagramConfidence(str(raw_confidence))
            except ValueError:
                return self._match_from_known_url(restaurant, url)
            return InstagramMatch(url=url, confidence=confidence)
        return None

    def _match_from_known_url(self, restaurant: Restaurant, url: str) -> InstagramMatch:
        handle = extract_handle(url) or ""
        full_name = ""
        biography = ""
        if self._profile_client is not None and handle:
            profile = self._profile_client.get_profile(handle)
            if profile is not None:
                full_name = profile.full_name
                biography = profile.biography
        confidence = classify_instagram_confidence(
            restaurant.name, restaurant.city, handle, full_name, biography
        )
        return InstagramMatch(url=url, confidence=confidence)

    def _search_instagram(self, restaurant: Restaurant) -> InstagramMatch | None:
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

            batch = self._extract_candidates(restaurant, results)
            if not batch:
                # Aucun handle Instagram exploitable : on essaie la formulation suivante.
                logger.debug(
                    "Aucun candidat Instagram pour %r avec la requête %r — cascade.",
                    restaurant.name,
                    query,
                )
                continue

            for handle, score in batch:
                if score > candidates.get(handle, -1):
                    candidates[handle] = score
            # Des résultats exploitables ont été trouvés : on arrête la cascade.
            break

        if not candidates:
            logger.debug("Aucun candidat Instagram trouvé pour %r.", restaurant.name)
            return None

        ranked = sorted(candidates.items(), key=lambda item: item[1], reverse=True)
        return self._select_best(restaurant, ranked)

    @staticmethod
    def _build_queries(restaurant: Restaurant) -> list[str]:
        """Cascade de requêtes, de la plus précise à la plus large.

        On ne passe à la suivante que si la précédente n'a renvoyé aucun
        handle Instagram exploitable (voir `_search_instagram`).
        """

        name = restaurant.name.strip()
        city = restaurant.city.strip()
        if not name:
            return []

        if city:
            return [
                f'site:instagram.com "{name}" "{city}"',
                f'"{name}" "{city}" instagram',
                f'"{name}" instagram site:instagram.com',
                f"{name} {city} instagram",
            ]
        return [
            f'site:instagram.com "{name}"',
            f'"{name}" instagram site:instagram.com',
            f'"{name}" instagram',
            f"{name} instagram",
        ]

    def _extract_candidates(
        self, restaurant: Restaurant, results: list[SearchResult]
    ) -> list[tuple[str, int]]:
        candidates: list[tuple[str, int]] = []
        seen_in_batch: set[str] = set()

        for result in results:
            handles: list[str] = []
            url_handle = extract_handle(result.url)
            if url_handle is not None:
                handles.append(url_handle)
            for text_handle in extract_handles_from_text(f"{result.title} {result.snippet}"):
                if text_handle.lower() not in {h.lower() for h in handles}:
                    handles.append(text_handle)

            if not handles:
                continue

            base_text = f"{result.title} {result.snippet}"
            for handle in handles:
                key = handle.lower()
                if key in seen_in_batch:
                    continue
                seen_in_batch.add(key)

                candidate_text = (
                    f"{base_text} {handle.replace('.', ' ').replace('_', ' ')}"
                )
                score = score_candidate(restaurant.name, candidate_text)
                score, _ = self._apply_city_bonus(restaurant, handle, score)
                candidates.append((handle, score))

        return candidates

    def _select_best(
        self, restaurant: Restaurant, ranked: list[tuple[str, int]]
    ) -> InstagramMatch | None:
        if self._profile_client is None:
            return self._best_by_text_only(restaurant, ranked, self._settings.instagram_match_threshold)

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
            url = to_profile_url(handle)
            assert url is not None
            confidence = classify_instagram_confidence(
                restaurant.name,
                restaurant.city,
                handle,
                profile.full_name,
                profile.biography,
            )

            if verified_score >= self._settings.instagram_match_threshold:
                logger.info(
                    "Instagram vérifié pour %r : @%s (score %d, confiance %s, %s follower(s)).",
                    restaurant.name,
                    handle,
                    verified_score,
                    confidence.value,
                    profile.follower_count,
                )
                return InstagramMatch(url=url, confidence=confidence)

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
            return self._best_by_text_only(restaurant, ranked, fallback_threshold)

        # Association incertaine : meilleur candidat textuel conservé en Faible
        # pour revue manuelle (fichier a_verifier), plutôt qu'écarté silencieusement.
        return self._uncertain_match(restaurant, ranked)

    def _best_by_text_only(
        self,
        restaurant: Restaurant,
        ranked: list[tuple[str, int]],
        threshold: int,
    ) -> InstagramMatch | None:
        if not ranked:
            return None
        handle, score = ranked[0]
        if score < threshold:
            return self._uncertain_match(restaurant, ranked)
        url = to_profile_url(handle)
        if url is None:
            return None
        confidence = classify_instagram_confidence(
            restaurant.name, restaurant.city, handle, "", ""
        )
        return InstagramMatch(url=url, confidence=confidence)

    def _uncertain_match(
        self, restaurant: Restaurant, ranked: list[tuple[str, int]]
    ) -> InstagramMatch | None:
        if not ranked:
            return None
        handle, score = ranked[0]
        if score < _MIN_UNCERTAIN_SCORE:
            logger.debug("Aucun profil Instagram vérifié pour %r.", restaurant.name)
            return None
        url = to_profile_url(handle)
        if url is None:
            return None
        logger.info(
            "Instagram incertain (Faible) pour %r : @%s (score texte %d).",
            restaurant.name,
            handle,
            score,
        )
        return InstagramMatch(url=url, confidence=InstagramConfidence.FAIBLE)

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
