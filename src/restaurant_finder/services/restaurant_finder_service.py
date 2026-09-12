"""Service d'orchestration : le seul point d'entrée de la logique métier.

`RestaurantFinderService` compose une `RestaurantSource` (récupération
des établissements), un `InstagramFinder` optionnel (enrichissement) et
un ensemble d'`Exporter`s. La CLI (ou toute autre couche de présentation
future, ex: une API) ne fait qu'appeler ce service : elle ne connaît ni
Overpass, ni DuckDuckGo, ni pandas.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from restaurant_finder.config import Settings
from restaurant_finder.domain.models import InstagramConfidence, Restaurant
from restaurant_finder.enrichment.instagram_finder import InstagramFinder, InstagramMatch
from restaurant_finder.enrichment.instagram_profile import InstagramProfileClient
from restaurant_finder.exceptions import RestaurantFinderError
from restaurant_finder.export.base import Exporter
from restaurant_finder.filtering.chain_filter import ChainRestaurantFilter
from restaurant_finder.filtering.cuisine_filter import CuisineFilter, parse_cuisine_values
from restaurant_finder.geocoding.geo_math import PointQuery
from restaurant_finder.progress import SearchProgress, compute_run_id, progress_dir_for
from restaurant_finder.sources.base import RestaurantSource
from restaurant_finder.utils.errors import log_and_continue

logger = logging.getLogger(__name__)

#: Callback appelé après chaque restaurant enrichi : (fait, total).
ProgressCallback = Callable[[int, int], None]


class RestaurantFinderService:
    """Orchestre la recherche, l'enrichissement et l'export des restaurants."""

    def __init__(
        self,
        source: RestaurantSource,
        settings: Settings,
        instagram_finder: InstagramFinder | None = None,
        follower_client: InstagramProfileClient | None = None,
        chain_filter: ChainRestaurantFilter | None = None,
        cuisine_filter: CuisineFilter | None = None,
    ) -> None:
        self._source = source
        self._settings = settings
        self._instagram_finder = instagram_finder
        self._follower_client = follower_client
        self._chain_filter = chain_filter or ChainRestaurantFilter()
        self._cuisine_filter = cuisine_filter

    def find_restaurants(
        self,
        cities: Sequence[str] | None = None,
        near_points: Sequence[PointQuery] | None = None,
        categories: Sequence[str] | None = None,
        limit: int | None = None,
        enrich_instagram: bool = True,
        exclude_chains: bool = True,
        cuisines: Sequence[str] | str | None = None,
        on_progress: ProgressCallback | None = None,
    ) -> list[Restaurant]:
        """Exécute le pipeline complet et retourne la liste des restaurants.

        Il faut fournir `cities`, `near_points`, ou les deux : les résultats
        de chaque ville et de chaque point sont fusionnés et dédupliqués par
        identifiant OSM. Ceci permet de combiner plusieurs villes et
        plusieurs lieux "pingués" (chacun avec son propre rayon) en une
        seule recherche étendue.

        `cuisines` : liste optionnelle de valeurs du tag OSM `cuisine` à
        conserver. Si omis (``None``), aucun filtre cuisine n'est appliqué.
        """

        if not cities and not near_points:
            raise ValueError(
                "Il faut fournir au moins une ville (cities) ou un point (near_points)."
            )

        categories = tuple(categories) if categories else self._settings.default_categories

        restaurants, total_sources, failures = self._fetch_from_all_sources(
            cities, near_points, categories
        )
        if not restaurants and failures and len(failures) == total_sources:
            # Toutes les sources ont échoué : remonter une erreur claire plutôt
            # que de laisser croire que la recherche n'a simplement rien trouvé.
            # S'il n'y avait qu'une seule source, on relève son erreur exacte
            # (ex: "Ville introuvable"), plus utile qu'un message générique.
            raise failures[0]
        restaurants = self._dedupe_by_osm_id(restaurants)

        cuisine_filter = self._resolve_cuisine_filter(cuisines)
        if cuisine_filter is not None:
            restaurants, cuisine_excluded = cuisine_filter.apply(restaurants)
            if cuisine_excluded:
                logger.info(
                    "%d établissement(s) exclu(s) par filtre cuisine (%s) — %d restant(s).",
                    cuisine_excluded,
                    ", ".join(sorted(cuisine_filter.allowed)),
                    len(restaurants),
                )

        if exclude_chains:
            restaurants, excluded = self._chain_filter.exclude_chains(restaurants)
            if excluded:
                logger.info(
                    "%d enseigne(s)/franchise(s) exclue(s) — %d indépendant(s) restant(s).",
                    excluded,
                    len(restaurants),
                )

        if limit is not None:
            restaurants = restaurants[:limit]

        if enrich_instagram and self._instagram_finder is not None and restaurants:
            restaurants = self.enrich_with_instagram(restaurants, on_progress)

        return restaurants

    def _fetch_from_all_sources(
        self,
        cities: Sequence[str] | None,
        near_points: Sequence[PointQuery] | None,
        categories: Sequence[str],
    ) -> tuple[list[Restaurant], int, list[RestaurantFinderError]]:
        """Interroge chaque ville et le lot de points GPS.

        Un échec isolé (une ville introuvable, un point sans résultat réseau)
        n'annule pas les autres sources. Retourne les restaurants trouvés, le
        nombre total de sources tentées, et la liste des échecs rencontrés.
        """

        restaurants: list[Restaurant] = []
        failures: list[RestaurantFinderError] = []
        total_sources = 0

        for city in cities or []:
            total_sources += 1
            try:
                restaurants.extend(self._source.find_restaurants(city, categories))
            except RestaurantFinderError as exc:
                failures.append(exc)
                log_and_continue(
                    logger,
                    subject=f"la ville {city!r}",
                    action="la récupération des établissements",
                    exc=exc,
                )

        if near_points:
            total_sources += 1
            try:
                restaurants.extend(
                    self._source.find_restaurants_near_points(near_points, categories)
                )
            except RestaurantFinderError as exc:
                failures.append(exc)
                log_and_continue(
                    logger,
                    subject="les points GPS (--near)",
                    action="la récupération des établissements",
                    exc=exc,
                )

        return restaurants, total_sources, failures

    def _resolve_cuisine_filter(
        self, cuisines: Sequence[str] | str | None
    ) -> CuisineFilter | None:
        if cuisines is None:
            return self._cuisine_filter
        if isinstance(cuisines, str):
            parsed = parse_cuisine_values(cuisines)
            return CuisineFilter(parsed) if parsed else None
        if not cuisines:
            return None
        return CuisineFilter(tuple(cuisines))

    @staticmethod
    def _dedupe_by_osm_id(restaurants: list[Restaurant]) -> list[Restaurant]:
        """Fusionne les résultats de plusieurs recherches (ville + points GPS)."""

        seen: set[str] = set()
        deduped: list[Restaurant] = []
        for restaurant in restaurants:
            if restaurant.osm_id in seen:
                continue
            seen.add(restaurant.osm_id)
            deduped.append(restaurant)
        return deduped

    def enrich_with_instagram(
        self,
        restaurants: list[Restaurant],
        on_progress: ProgressCallback | None = None,
        resume: bool = True,
    ) -> list[Restaurant]:
        """Recherche Instagram, puis filtre selon le nombre de followers.

        Reprise après interruption : la progression (résultat Instagram par
        établissement) est sauvegardée sur disque après chaque établissement
        traité. Si un run précédent sur exactement le même lot de restaurants
        (mêmes `osm_id`, mêmes réglages de filtre followers) a été interrompu
        (Ctrl+C, plantage), les établissements déjà traités sont réappliqués
        directement, sans nouvel appel réseau. `resume=False` (`--fresh`)
        ignore et efface toute progression existante avant de démarrer.
        """

        if self._instagram_finder is None:
            logger.warning("Enrichissement Instagram demandé mais aucun finder configuré.")
            return restaurants

        total = len(restaurants)
        completed = 0

        progress = SearchProgress(
            progress_dir_for(self._settings.cache_dir),
            compute_run_id(
                (r.osm_id for r in restaurants),
                self._settings.instagram_max_followers,
                self._settings.instagram_filter_by_followers,
                self._settings.instagram_exclude_unknown_followers,
                self._settings.instagram_match_threshold,
            ),
        )
        saved = progress.load() if resume else {}
        if not resume:
            progress.clear()

        pending: list[Restaurant] = []
        for restaurant in restaurants:
            saved_fields = saved.get(restaurant.osm_id)
            if saved_fields is None:
                pending.append(restaurant)
                continue
            _apply_saved_instagram_fields(restaurant, saved_fields)
            completed += 1

        if completed:
            logger.info(
                "Reprise : %d/%d établissement(s) déjà traité(s) lors d'une exécution "
                "précédente (%s).",
                completed,
                total,
                progress.path,
            )
            if on_progress is not None:
                on_progress(completed, total)

        if not pending:
            progress.clear()
            return restaurants

        max_workers = max(1, self._settings.instagram_search_max_workers)
        executor = ThreadPoolExecutor(max_workers=max_workers)
        try:
            future_to_restaurant = {
                executor.submit(self._resolve_instagram, restaurant): restaurant
                for restaurant in pending
            }

            try:
                for future in as_completed(future_to_restaurant):
                    restaurant = future_to_restaurant[future]
                    try:
                        match, followers = future.result()
                        _assign_instagram_result(restaurant, match, followers)
                    except Exception as exc:  # noqa: BLE001 - on ne bloque jamais le pipeline
                        log_and_continue(
                            logger,
                            subject=f"le restaurant {restaurant.name!r}",
                            action="la recherche Instagram",
                            exc=exc,
                        )
                        restaurant.instagram_url = None
                        restaurant.instagram_followers = None
                        restaurant.instagram_confidence = None
                    finally:
                        completed += 1
                        progress.mark_done(
                            restaurant.osm_id, _saved_instagram_fields(restaurant)
                        )
                        logger.debug(
                            "Restaurant traité (%d/%d) : %r.",
                            completed,
                            total,
                            restaurant.name,
                        )
                        if on_progress is not None:
                            on_progress(completed, total)
            except KeyboardInterrupt:
                logger.warning(
                    "Recherche interrompue par l'utilisateur (%d/%d établissement(s) "
                    "traité(s)) — progression sauvegardée dans %s. Relance la même "
                    "commande pour reprendre.",
                    completed,
                    total,
                    progress.path,
                )
                # N'annule que les tâches pas encore démarrées : celles déjà en
                # cours ont le temps de se terminer proprement (voir `finally`
                # ci-dessous), plutôt que de rester bloqué indéfiniment.
                executor.shutdown(wait=False, cancel_futures=True)
                raise
        finally:
            executor.shutdown(wait=True)

        # Tout le lot est allé au bout : la sauvegarde de reprise n'a plus d'utilité.
        progress.clear()
        return restaurants

    def _resolve_instagram(
        self, restaurant: Restaurant
    ) -> tuple[InstagramMatch | None, int | None]:
        assert self._instagram_finder is not None
        match = self._instagram_finder.find(restaurant)
        if match is None:
            return None, None

        if (
            not self._settings.instagram_filter_by_followers
            or self._follower_client is None
        ):
            return match, None

        followers = self._follower_client.get_follower_count(match.url)
        if followers is None:
            if self._settings.instagram_exclude_unknown_followers:
                logger.info(
                    "Instagram @%s exclu : nombre de followers illisible.",
                    extract_handle_safe(match.url),
                )
                return None, None
            return match, None

        if followers >= self._settings.instagram_max_followers:
            handle = extract_handle_safe(match.url)
            logger.info(
                "Instagram @%s exclu : %d followers (>= %d).",
                handle,
                followers,
                self._settings.instagram_max_followers,
            )
            return None, followers

        return match, followers

    @staticmethod
    def split_by_instagram_confidence(
        restaurants: list[Restaurant],
    ) -> tuple[list[Restaurant], list[Restaurant]]:
        """Sépare les résultats principaux des associations à revoir manuellement.

        - **Principaux** : sans Instagram, ou confiance **Élevé** uniquement.
          Les Instagram Moyen / Faible sont retirés (URL / confiance vidées)
          pour l'export principal.
        - **À vérifier** : établissements dont l'Instagram est noté Moyen ou
          Faible (copie avec l'association intacte → ``a_verifier.csv``).
        """

        trusted: list[Restaurant] = []
        to_review: list[Restaurant] = []
        review_levels = {InstagramConfidence.MOYEN, InstagramConfidence.FAIBLE}

        for restaurant in restaurants:
            if restaurant.instagram_confidence in review_levels:
                to_review.append(restaurant.model_copy(deep=True))
                cleaned = restaurant.model_copy(deep=True)
                cleaned.instagram_url = None
                cleaned.instagram_followers = None
                cleaned.instagram_confidence = None
                trusted.append(cleaned)
            else:
                trusted.append(restaurant)

        return trusted, to_review

    @staticmethod
    def export(
        restaurants: list[Restaurant],
        exporters: Sequence[Exporter],
        destination: Path,
    ) -> list[Path]:
        """Exporte `restaurants` avec chaque exporteur fourni, vers `destination`."""

        return [exporter.export(restaurants, destination) for exporter in exporters]


def extract_handle_safe(url: str) -> str:
    from restaurant_finder.enrichment.instagram_normalize import extract_handle

    return extract_handle(url) or "?"


def _assign_instagram_result(
    restaurant: Restaurant, match: InstagramMatch | None, followers: int | None
) -> None:
    """Applique le résultat d'une recherche Instagram sur `restaurant`."""

    if match is None:
        restaurant.instagram_url = None
        restaurant.instagram_confidence = None
        # Conservé quand le compte est exclu pour trop de followers.
        restaurant.instagram_followers = followers
    else:
        restaurant.instagram_url = match.url
        restaurant.instagram_confidence = match.confidence
        restaurant.instagram_followers = followers


def _saved_instagram_fields(restaurant: Restaurant) -> dict[str, object]:
    """Sérialise les champs Instagram d'un restaurant pour le fichier de progression."""

    return {
        "instagram_url": restaurant.instagram_url,
        "instagram_followers": restaurant.instagram_followers,
        "instagram_confidence": (
            restaurant.instagram_confidence.value if restaurant.instagram_confidence else None
        ),
    }


def _apply_saved_instagram_fields(restaurant: Restaurant, fields: dict[str, object]) -> None:
    """Réapplique sur `restaurant` un résultat Instagram sauvegardé (reprise)."""

    raw_url = fields.get("instagram_url")
    restaurant.instagram_url = str(raw_url) if raw_url else None

    raw_followers = fields.get("instagram_followers")
    restaurant.instagram_followers = (
        int(raw_followers) if isinstance(raw_followers, int) else None
    )

    raw_confidence = fields.get("instagram_confidence")
    try:
        restaurant.instagram_confidence = (
            InstagramConfidence(str(raw_confidence)) if raw_confidence else None
        )
    except ValueError:
        restaurant.instagram_confidence = None
