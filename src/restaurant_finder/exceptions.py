"""Exceptions métier de Restaurant Finder.

Centraliser les exceptions permet à la CLI (ou toute future couche de
présentation) de gérer les erreurs de façon uniforme, sans dépendre des
détails d'implémentation de chaque couche technique.
"""

from __future__ import annotations


class RestaurantFinderError(Exception):
    """Exception racine de l'application."""


class GeocodingError(RestaurantFinderError):
    """Levée quand une ville ne peut pas être géolocalisée."""


class RestaurantSourceError(RestaurantFinderError):
    """Levée quand une source de données de restaurants échoue."""


class SearchProviderError(RestaurantFinderError):
    """Levée quand un fournisseur de recherche web échoue."""


class ExportError(RestaurantFinderError):
    """Levée quand l'export d'un fichier (CSV, Excel...) échoue."""
