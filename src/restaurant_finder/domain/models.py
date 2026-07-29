"""Modèles de domaine.

Ces modèles sont le cœur de l'application : ils ne dépendent d'aucune
librairie de scraping, d'export ou de CLI. Toutes les autres couches
convergent vers (ou partent de) `Restaurant`.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    """Zone géographique rectangulaire (utilisée pour interroger Overpass)."""

    south: float
    north: float
    west: float
    east: float


class Restaurant(BaseModel):
    """Représente un restaurant (ou café, bar, fast-food...) identifié."""

    osm_id: str = Field(description="Identifiant unique OpenStreetMap, ex: 'node/12345'.")
    name: str
    category: str = Field(description="Libellé de catégorie en français, ex: 'Restaurant'.")
    address: str = ""
    city: str = ""
    latitude: float | None = None
    longitude: float | None = None
    instagram_url: str | None = None

    def to_export_row(self) -> dict[str, str]:
        """Convertit le restaurant en ligne prête pour l'export (CSV/Excel).

        Les noms de colonnes correspondent exactement au format de sortie
        attendu : Nom, Instagram, Adresse, Ville, Catégorie.
        """

        return {
            "Nom": self.name,
            "Instagram": self.instagram_url or "",
            "Adresse": self.address,
            "Ville": self.city,
            "Catégorie": self.category,
        }
