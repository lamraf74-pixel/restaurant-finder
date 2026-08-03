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
from restaurant_finder.domain.models import Restaurant
from restaurant_finder.enrichment.instagram_finder import InstagramFinder
from restaurant_finder.enrichment.instagram_followers import InstagramFollowerClient
from restaurant_finder.export.base import Exporter
from restaurant_finder.filtering.chain_filter import ChainRestaurantFilter
from restaurant_finder.geocoding.geo_math import PointQuery
from restaurant_finder.sources.base import RestaurantSource

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
        follower_client: InstagramFollowerClient | None = None,
        chain_filter: ChainRestaurantFilter | None = None,
    ) -> None:
        self._source = source
        self._settings = settings
        self._instagram_finder = instagram_finder
        self._follower_client = follower_client
        self._chain_filter = chain_filter or ChainRestaurantFilter()

    def find_restaurants(
        self,
        cities: Sequence[str] | None = None,
        near_points: Sequence[PointQuery] | None = None,
        categories: Sequence[str] | None = None,
        limit: int | None = None,
        enrich_instagram: bool = True,
        exclude_chains: bool = True,
        on_progress: ProgressCallback | None = None,
    ) -> list[Restaurant]:
        """Exécute le pipeline complet et retourne la liste des restaurants.

        Il faut fournir `cities`, `near_points`, ou les deux : les résultats
        de chaque ville et de chaque point sont fusionnés et dédupliqués par
        identifiant OSM. Ceci permet de combiner plusieurs villes et
        plusieurs lieux "pingués" (chacun avec son propre rayon) en une
        seule recherche étendue.
        """

        if not cities and not near_points:
            raise ValueError(
                "Il faut fournir au moins une ville (cities) ou un point (near_points)."
            )

        categories = tuple(categories) if categories else self._settings.default_categories

        restaurants: list[Restaurant] = []
        for city in cities or []:
            restaurants.extend(self._source.find_restaurants(city, categories))
        if near_points:
            restaurants.extend(
                self._source.find_restaurants_near_points(near_points, categories)
            )
        restaurants = self._dedupe_by_osm_id(restaurants)

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
    ) -> list[Restaurant]:
        """Recherche Instagram, puis filtre selon le nombre de followers."""

        if self._instagram_finder is None:
            logger.warning("Enrichissement Instagram demandé mais aucun finder configuré.")
            return restaurants

        total = len(restaurants)
        completed = 0

        max_workers = max(1, self._settings.instagram_search_max_workers)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_restaurant = {
                executor.submit(self._resolve_instagram, restaurant): restaurant
                for restaurant in restaurants
            }

            for future in as_completed(future_to_restaurant):
                restaurant = future_to_restaurant[future]
                try:
                    url, followers = future.result()
                    restaurant.instagram_url = url
                    restaurant.instagram_followers = followers
                except Exception:  # noqa: BLE001 - on ne bloque jamais le pipeline
                    logger.exception(
                        "Erreur inattendue lors de la recherche Instagram pour %r.",
                        restaurant.name,
                    )
                    restaurant.instagram_url = None
                    restaurant.instagram_followers = None
                finally:
                    completed += 1
                    if on_progress is not None:
                        on_progress(completed, total)

        return restaurants

    def _resolve_instagram(self, restaurant: Restaurant) -> tuple[str | None, int | None]:
        assert self._instagram_finder is not None
        url = self._instagram_finder.find(restaurant)
        if url is None:
            return None, None

        if (
            not self._settings.instagram_filter_by_followers
            or self._follower_client is None
        ):
            return url, None

        followers = self._follower_client.get_follower_count(url)
        if followers is None:
            if self._settings.instagram_exclude_unknown_followers:
                logger.info(
                    "Instagram @%s exclu : nombre de followers illisible.",
                    extract_handle_safe(url),
                )
                return None, None
            return url, None

        if followers >= self._settings.instagram_max_followers:
            handle = extract_handle_safe(url)
            logger.info(
                "Instagram @%s exclu : %d followers (>= %d).",
                handle,
                followers,
                self._settings.instagram_max_followers,
            )
            return None, followers

        return url, followers

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
