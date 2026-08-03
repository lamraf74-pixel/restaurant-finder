"""Calculs géométriques simples pour les recherches centrées sur un point.

Approximations volontairement légères (pas de dépendance type geopy) :
suffisantes pour construire une bounding box autour d'un point GPS et
pour filtrer des résultats par distance à vol d'oiseau.
"""

from __future__ import annotations

import math
from typing import NamedTuple

from restaurant_finder.domain.models import BoundingBox

#: Mètres par degré de latitude (quasi constant sur Terre).
_METERS_PER_DEGREE_LATITUDE = 111_320.0
_EARTH_RADIUS_METERS = 6_371_000.0


class PointQuery(NamedTuple):
    """Un lieu "pingué" (ex: sur Google Maps ou sur la carte du panel web).

    Chaque point porte son propre rayon, ce qui permet à l'utilisateur de
    cibler précisément une zone dense avec un petit rayon et une zone plus
    large avec un rayon plus grand, dans la même recherche.
    """

    latitude: float
    longitude: float
    radius_meters: float


def bbox_from_point(latitude: float, longitude: float, radius_meters: float) -> BoundingBox:
    """Construit une bounding box carrée englobant un cercle de rayon donné."""

    lat_delta = radius_meters / _METERS_PER_DEGREE_LATITUDE
    lon_scale = max(math.cos(math.radians(latitude)), 1e-6)
    lon_delta = radius_meters / (_METERS_PER_DEGREE_LATITUDE * lon_scale)

    return BoundingBox(
        south=latitude - lat_delta,
        north=latitude + lat_delta,
        west=longitude - lon_delta,
        east=longitude + lon_delta,
    )


def haversine_distance_meters(
    latitude1: float, longitude1: float, latitude2: float, longitude2: float
) -> float:
    """Distance à vol d'oiseau (en mètres) entre deux points GPS."""

    phi1, phi2 = math.radians(latitude1), math.radians(latitude2)
    delta_phi = math.radians(latitude2 - latitude1)
    delta_lambda = math.radians(longitude2 - longitude1)

    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_METERS * math.asin(math.sqrt(a))
