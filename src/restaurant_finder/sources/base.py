"""Interface abstraite d'une source de données de restaurants.

Toute nouvelle source (Google Places, Yelp, import CSV manuel...) doit
implémenter ce contrat pour être utilisable par `RestaurantFinderService`
sans aucune modification du reste du code (principe ouvert/fermé).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from restaurant_finder.domain.models import Restaurant
from restaurant_finder.geocoding.geo_math import PointQuery


class RestaurantSource(ABC):
    """Contrat pour toute source capable de lister des restaurants."""

    @abstractmethod
    def find_restaurants(self, city: str, categories: Sequence[str]) -> list[Restaurant]:
        """Retourne les restaurants de `city` correspondant à `categories`.

        Args:
            city: nom de la ville à rechercher.
            categories: liste de catégories OSM (ex: "restaurant", "cafe").
        """
        raise NotImplementedError

    @abstractmethod
    def find_restaurants_near_points(
        self,
        points: Sequence[PointQuery],
        categories: Sequence[str],
    ) -> list[Restaurant]:
        """Retourne les restaurants situés dans le rayon de chaque point.

        Args:
            points: lieux "pingués" (latitude, longitude, rayon en mètres).
                Plusieurs points étendent la zone de recherche à plusieurs
                endroits distincts, chacun avec son propre rayon.
            categories: liste de catégories OSM (ex: "restaurant", "cafe").
        """
        raise NotImplementedError
