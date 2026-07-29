"""Interface abstraite d'une source de données de restaurants.

Toute nouvelle source (Google Places, Yelp, import CSV manuel...) doit
implémenter ce contrat pour être utilisable par `RestaurantFinderService`
sans aucune modification du reste du code (principe ouvert/fermé).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence

from restaurant_finder.domain.models import Restaurant


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
