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
from restaurant_finder.export.base import Exporter
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
    ) -> None:
        self._source = source
        self._settings = settings
        self._instagram_finder = instagram_finder

    def find_restaurants(
        self,
        city: str,
        categories: Sequence[str] | None = None,
        limit: int | None = None,
        enrich_instagram: bool = True,
        on_progress: ProgressCallback | None = None,
    ) -> list[Restaurant]:
        """Exécute le pipeline complet et retourne la liste des restaurants.

        Args:
            city: ville à rechercher.
            categories: catégories OSM à inclure (défaut : configuration).
            limit: nombre maximal de restaurants à retourner.
            enrich_instagram: active la recherche du profil Instagram.
            on_progress: callback optionnel pour suivre l'avancement de
                l'enrichissement (utilisé par la CLI pour la barre de progression).
        """

        categories = tuple(categories) if categories else self._settings.default_categories

        restaurants = self._source.find_restaurants(city, categories)

        if limit is not None:
            restaurants = restaurants[:limit]

        if enrich_instagram and self._instagram_finder is not None and restaurants:
            restaurants = self.enrich_with_instagram(restaurants, on_progress)

        return restaurants

    def enrich_with_instagram(
        self,
        restaurants: list[Restaurant],
        on_progress: ProgressCallback | None = None,
    ) -> list[Restaurant]:
        """Recherche et renseigne le profil Instagram de chaque restaurant.

        Exposée séparément de `find_restaurants` pour permettre à la couche
        de présentation (CLI) d'afficher une barre de progression dédiée à
        cette étape, la plus longue du pipeline.
        """

        if self._instagram_finder is None:
            logger.warning("Enrichissement Instagram demandé mais aucun finder configuré.")
            return restaurants

        total = len(restaurants)
        completed = 0

        max_workers = max(1, self._settings.instagram_search_max_workers)
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_restaurant = {
                executor.submit(self._instagram_finder.find, restaurant): restaurant
                for restaurant in restaurants
            }

            for future in as_completed(future_to_restaurant):
                restaurant = future_to_restaurant[future]
                try:
                    restaurant.instagram_url = future.result()
                except Exception:  # noqa: BLE001 - on ne bloque jamais le pipeline
                    logger.exception(
                        "Erreur inattendue lors de la recherche Instagram pour %r.",
                        restaurant.name,
                    )
                    restaurant.instagram_url = None
                finally:
                    completed += 1
                    if on_progress is not None:
                        on_progress(completed, total)

        return restaurants

    @staticmethod
    def export(
        restaurants: list[Restaurant],
        exporters: Sequence[Exporter],
        destination: Path,
    ) -> list[Path]:
        """Exporte `restaurants` avec chaque exporteur fourni, vers `destination`."""

        return [exporter.export(restaurants, destination) for exporter in exporters]
