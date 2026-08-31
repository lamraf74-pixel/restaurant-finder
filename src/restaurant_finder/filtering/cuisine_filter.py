"""Filtre des restaurants selon le tag OSM `cuisine`."""

from __future__ import annotations

from restaurant_finder.domain.models import Restaurant
from restaurant_finder.utils.text import normalize_text

#: Exemples de valeurs courantes (utilisés dans l'aide CLI, pas appliqués par défaut).
DEFAULT_CUISINES: tuple[str, ...] = (
    "bistro",
    "pizza",
    "sandwich",
    "cafe",
    "brunch",
)


def parse_cuisine_values(raw: str | None) -> tuple[str, ...] | None:
    """Parse une liste CSV de cuisines (`pizza,cafe`) en tuple normalisé.

    Retourne ``None`` si ``raw`` est vide / absent (pas de filtre à appliquer).
    """

    if raw is None or not raw.strip():
        return None
    values = [normalize_text(part).replace(" ", "_") for part in raw.split(",")]
    cleaned = tuple(value for value in values if value)
    return cleaned or None


class CuisineFilter:
    """Ne conserve que les établissements dont le tag `cuisine` matche la liste."""

    def __init__(self, allowed: tuple[str, ...]) -> None:
        if not allowed:
            raise ValueError("CuisineFilter exige au moins une valeur de cuisine.")
        self._allowed = {normalize_text(value).replace(" ", "_") for value in allowed if value}
        if not self._allowed:
            raise ValueError("CuisineFilter exige au moins une valeur de cuisine.")

    @property
    def allowed(self) -> frozenset[str]:
        return frozenset(self._allowed)

    def matches(self, restaurant: Restaurant) -> bool:
        """True si au moins une valeur du tag cuisine est dans la liste autorisée."""

        if not restaurant.cuisine:
            return False
        parts = [
            normalize_text(part).replace(" ", "_")
            for part in restaurant.cuisine.replace(",", ";").split(";")
        ]
        return any(part in self._allowed for part in parts if part)

    def apply(self, restaurants: list[Restaurant]) -> tuple[list[Restaurant], int]:
        """Retourne (conservés, nombre_exclus)."""

        kept: list[Restaurant] = []
        excluded = 0
        for restaurant in restaurants:
            if self.matches(restaurant):
                kept.append(restaurant)
            else:
                excluded += 1
        return kept, excluded
