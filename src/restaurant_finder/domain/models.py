"""Modèles de domaine.

Ces modèles sont le cœur de l'application : ils ne dépendent d'aucune
librairie de scraping, d'export ou de CLI. Toutes les autres couches
convergent vers (ou partent de) `Restaurant`.
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    """Zone géographique rectangulaire (utilisée pour interroger Overpass)."""

    south: float
    north: float
    west: float
    east: float


class InstagramConfidence(str, Enum):
    """Niveau de confiance d'une association restaurant ↔ Instagram."""

    ELEVE = "Élevé"
    MOYEN = "Moyen"
    FAIBLE = "Faible"


class Restaurant(BaseModel):
    """Représente un restaurant (ou café, bar, fast-food...) identifié."""

    osm_id: str = Field(description="Identifiant unique OpenStreetMap, ex: 'node/12345'.")
    name: str
    category: str = Field(description="Libellé de catégorie en français, ex: 'Restaurant'.")
    address: str = ""
    city: str = ""
    latitude: float | None = None
    longitude: float | None = None
    brand: str | None = Field(
        default=None,
        description="Enseigne OSM (`brand`) si renseignée — utile pour détecter les chaînes.",
    )
    operator: str | None = Field(
        default=None,
        description="Opérateur OSM (`operator`) si renseigné.",
    )
    cuisine: str | None = Field(
        default=None,
        description="Tag OSM `cuisine` brut (peut contenir plusieurs valeurs séparées par `;`).",
    )
    website: str | None = Field(
        default=None,
        description="Site web OSM (`website`) si renseigné.",
    )
    instagram_url: str | None = None
    instagram_followers: int | None = Field(
        default=None,
        description="Nombre de followers Instagram, si disponible.",
    )
    instagram_confidence: InstagramConfidence | None = Field(
        default=None,
        description="Niveau de confiance de l'association Instagram (Élevé / Moyen / Faible).",
    )

    @property
    def instagram_handle(self) -> str | None:
        """Retourne uniquement le nom du compte Instagram (sans URL)."""

        # Import local pour éviter une dépendance circulaire domain ↔ enrichment.
        from restaurant_finder.enrichment.instagram_normalize import extract_handle

        return extract_handle(self.instagram_url)

    def to_export_row(self) -> dict[str, str]:
        """Convertit le restaurant en ligne prête pour l'export (CSV/Excel).

        Les noms de colonnes correspondent exactement au format de sortie
        attendu : Nom, Instagram, Adresse, Ville, Catégorie, Confiance.
        La colonne Instagram contient le handle (ex: bistrot_le_cerey), pas l'URL.
        """

        return {
            "Nom": self.name,
            "Instagram": self.instagram_handle or "",
            "Adresse": self.address,
            "Ville": self.city,
            "Catégorie": self.category,
            "Confiance": (
                self.instagram_confidence.value if self.instagram_confidence else ""
            ),
        }
