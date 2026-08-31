"""Source de restaurants basée sur l'API Overpass (données OpenStreetMap).

Deux modes de recherche :
1. Par ville : nom de ville -> bounding box (Nominatim) -> requête Overpass.
2. Par point GPS ("pin" Google Maps) : point + rayon -> bounding box ->
   requête Overpass -> filtrage précis par distance à vol d'oiseau.
   Plusieurs points peuvent être combinés pour étendre la recherche.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Sequence

import requests

from restaurant_finder.config import DEFAULT_CATEGORY_LABELS, Settings
from restaurant_finder.domain.models import BoundingBox, Restaurant
from restaurant_finder.enrichment.instagram_normalize import to_profile_url
from restaurant_finder.exceptions import RestaurantSourceError
from restaurant_finder.geocoding.geo_math import (
    PointQuery,
    bbox_from_point,
    haversine_distance_meters,
)
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

#: Un timestamp OSM valide ressemble à "2026-07-29T22:17:47Z".
_VALID_OSM_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T")


class OverpassRestaurantSource(RestaurantSource):
    """Récupère les restaurants d'une zone via Overpass (OpenStreetMap)."""

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
        restaurants = self._search_bbox(bbox, categories, fallback_city=city)
        logger.info("%d établissement(s) trouvé(s) à %s.", len(restaurants), city)
        return restaurants

    def find_restaurants_near_points(
        self,
        points: Sequence[PointQuery],
        categories: Sequence[str],
    ) -> list[Restaurant]:
        restaurants: list[Restaurant] = []
        seen_osm_ids: set[str] = set()

        for index, point in enumerate(points, start=1):
            bbox = bbox_from_point(point.latitude, point.longitude, point.radius_meters)
            label = (
                self._geocoder.reverse_geocode_city(point.latitude, point.longitude)
                or f"Lieu {index}"
            )

            found_here = 0
            for restaurant in self._search_bbox(bbox, categories, fallback_city=label):
                if restaurant.osm_id in seen_osm_ids:
                    continue

                if restaurant.latitude is not None and restaurant.longitude is not None:
                    distance = haversine_distance_meters(
                        point.latitude, point.longitude, restaurant.latitude, restaurant.longitude
                    )
                    if distance > point.radius_meters:
                        continue

                seen_osm_ids.add(restaurant.osm_id)
                restaurants.append(restaurant)
                found_here += 1

            logger.info(
                "%d établissement(s) trouvé(s) autour de (%.5f, %.5f) [%s, rayon %.0fm].",
                found_here,
                point.latitude,
                point.longitude,
                label,
                point.radius_meters,
            )

            if index < len(points):
                time.sleep(self._settings.overpass_rate_limit_seconds)

        return restaurants

    def _search_bbox(
        self, bbox: BoundingBox, categories: Sequence[str], fallback_city: str
    ) -> list[Restaurant]:
        elements = self._query_overpass(bbox, categories)

        restaurants: list[Restaurant] = []
        skipped = 0
        for element in elements:
            restaurant = self._parse_element(element, fallback_city=fallback_city)
            if restaurant is None:
                skipped += 1
                continue
            restaurants.append(restaurant)

        if skipped:
            logger.debug("%d éléments OSM ignorés (pas de nom exploitable).", skipped)

        return restaurants

    def _query_overpass(self, bbox: BoundingBox, categories: Sequence[str]) -> list[dict]:
        categories_pattern = "|".join(categories)
        query = _OVERPASS_QUERY_TEMPLATE.format(
            timeout=self._settings.overpass_timeout_seconds,
            categories=categories_pattern,
            south=bbox.south,
            west=bbox.west,
            north=bbox.north,
            east=bbox.east,
        )

        endpoints = (self._settings.overpass_base_url, *self._settings.overpass_fallback_urls)
        timeout = (
            self._settings.overpass_connect_timeout_seconds,
            self._settings.overpass_timeout_seconds,
        )
        last_error: Exception | None = None

        for endpoint in endpoints:
            try:
                elements = self._query_endpoint(endpoint, query, timeout)
            except (requests.RequestException, ValueError, RestaurantSourceError) as exc:
                logger.warning("Miroir Overpass indisponible (%s) : %s", endpoint, exc)
                last_error = exc
                continue

            return elements

        raise RestaurantSourceError(
            "Échec de la requête Overpass sur tous les miroirs disponibles. "
            "Les serveurs OpenStreetMap publics sont probablement saturés : "
            f"réessaie dans 1–2 minutes. Détail : {last_error}"
        ) from last_error

    def _query_endpoint(
        self,
        endpoint: str,
        query: str,
        timeout: tuple[float, float],
    ) -> list[dict]:
        """Interroge un miroir ; en cas de saturation (406/429), réessaie une fois."""

        attempts = 2
        for attempt in range(1, attempts + 1):
            logger.info(
                "Interrogation Overpass via %s (essai %d/%d)...",
                endpoint,
                attempt,
                attempts,
            )
            response = self._session.post(endpoint, data={"data": query}, timeout=timeout)

            if response.status_code in {406, 429, 504} and attempt < attempts:
                wait = self._settings.overpass_busy_retry_seconds
                logger.warning(
                    "Miroir %s saturé (HTTP %d). Nouvelle tentative dans %.0fs...",
                    endpoint,
                    response.status_code,
                    wait,
                )
                time.sleep(wait)
                continue

            response.raise_for_status()
            payload = response.json()
            self._ensure_payload_is_usable(endpoint, payload)
            return payload.get("elements", [])

        raise RestaurantSourceError(f"Miroir Overpass saturé : {endpoint}")

    @staticmethod
    def _ensure_payload_is_usable(endpoint: str, payload: dict) -> None:
        """Écarte les miroirs qui répondent 200 avec une base OSM invalide."""

        timestamp = str((payload.get("osm3s") or {}).get("timestamp_osm_base") or "")
        if not _VALID_OSM_TIMESTAMP.match(timestamp):
            raise RestaurantSourceError(
                f"Réponse Overpass invalide sur {endpoint} "
                f"(timestamp_osm_base={timestamp!r}). Miroir probablement hors service."
            )

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
        instagram_url = to_profile_url(
            tags.get("contact:instagram") or tags.get("instagram")
        )

        return Restaurant(
            osm_id=osm_id,
            name=name,
            category=category,
            address=address,
            city=city,
            latitude=latitude,
            longitude=longitude,
            brand=tags.get("brand"),
            operator=tags.get("operator"),
            cuisine=tags.get("cuisine"),
            website=tags.get("website"),
            instagram_url=instagram_url,
        )
