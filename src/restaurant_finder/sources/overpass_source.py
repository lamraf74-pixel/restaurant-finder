"""Source de restaurants basée sur l'API Overpass (données OpenStreetMap).

Pipeline : nom de ville -> bounding box (Nominatim) -> requête Overpass QL
sur cette zone -> parsing des éléments OSM en objets `Restaurant`.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import requests

from restaurant_finder.config import DEFAULT_CATEGORY_LABELS, Settings
from restaurant_finder.domain.models import BoundingBox, Restaurant
from restaurant_finder.exceptions import RestaurantSourceError
from restaurant_finder.geocoding.nominatim_client import NominatimGeocoder
from restaurant_finder.sources.base import RestaurantSource
from restaurant_finder.utils.text import join_non_empty

logger = logging.getLogger(__name__)

_OVERPASS_QUERY_TEMPLATE = """
[out:json][timeout:{timeout}];
(
  node["amenity"~"^({categories})$"]({south},{west},{north},{east});
  way["amenity"~"^({categories})$"]({south},{west},{north},{east});
  relation["amenity"~"^({categories})$"]({south},{west},{north},{east});
);
out center tags;
"""


class OverpassRestaurantSource(RestaurantSource):
    """Récupère les restaurants d'une ville via Overpass (OpenStreetMap)."""

    def __init__(
        self,
        session: requests.Session,
        settings: Settings,
        geocoder: NominatimGeocoder,
    ) -> None:
        self._session = session
        self._settings = settings
        self._geocoder = geocoder

    def find_restaurants(self, city: str, categories: Sequence[str]) -> list[Restaurant]:
        bbox = self._geocoder.geocode_city(city)
        elements = self._query_overpass(bbox, categories)

        restaurants: list[Restaurant] = []
        skipped = 0
        for element in elements:
            restaurant = self._parse_element(element, fallback_city=city)
            if restaurant is None:
                skipped += 1
                continue
            restaurants.append(restaurant)

        if skipped:
            logger.debug("%d éléments OSM ignorés (pas de nom exploitable).", skipped)

        logger.info("%d établissement(s) trouvé(s) à %s.", len(restaurants), city)
        return restaurants

    def _query_overpass(self, bbox: BoundingBox, categories: Sequence[str]) -> list[dict]:
        categories_pattern = "|".join(categories)
        query = _OVERPASS_QUERY_TEMPLATE.format(
            timeout=self._settings.request_timeout_seconds,
            categories=categories_pattern,
            south=bbox.south,
            west=bbox.west,
            north=bbox.north,
            east=bbox.east,
        )

        endpoints = (self._settings.overpass_base_url, *self._settings.overpass_fallback_urls)
        last_error: Exception | None = None

        for endpoint in endpoints:
            try:
                response = self._session.post(
                    endpoint,
                    data={"data": query},
                    timeout=self._settings.request_timeout_seconds,
                )
                response.raise_for_status()
                payload = response.json()
            except (requests.RequestException, ValueError) as exc:
                logger.warning("Miroir Overpass indisponible (%s) : %s", endpoint, exc)
                last_error = exc
                continue

            return payload.get("elements", [])

        raise RestaurantSourceError(
            f"Échec de la requête Overpass sur tous les miroirs disponibles : {last_error}"
        ) from last_error

    @staticmethod
    def _parse_element(element: dict, fallback_city: str) -> Restaurant | None:
        tags: dict = element.get("tags", {})
        name = tags.get("name")
        if not name:
            return None

        latitude = element.get("lat")
        longitude = element.get("lon")
        if latitude is None or longitude is None:
            center = element.get("center") or {}
            latitude = center.get("lat")
            longitude = center.get("lon")

        amenity = tags.get("amenity", "")
        category = DEFAULT_CATEGORY_LABELS.get(amenity, amenity.replace("_", " ").capitalize())

        street_line = join_non_empty([tags.get("addr:housenumber"), tags.get("addr:street")], " ")
        address = join_non_empty([street_line, tags.get("addr:postcode")])

        city = tags.get("addr:city") or fallback_city

        osm_id = f"{element.get('type', 'node')}/{element.get('id')}"

        return Restaurant(
            osm_id=osm_id,
            name=name,
            category=category,
            address=address,
            city=city,
            latitude=latitude,
            longitude=longitude,
        )
