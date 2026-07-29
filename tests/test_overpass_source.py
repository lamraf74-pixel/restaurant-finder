"""Tests de la source de restaurants Overpass (OpenStreetMap)."""

from __future__ import annotations

import requests
import responses

from restaurant_finder.config import Settings
from restaurant_finder.domain.models import BoundingBox
from restaurant_finder.sources.overpass_source import OverpassRestaurantSource


class _StubGeocoder:
    """Remplace `NominatimGeocoder` pour isoler le test de la source Overpass."""

    def __init__(self, bbox: BoundingBox) -> None:
        self._bbox = bbox

    def geocode_city(self, city: str) -> BoundingBox:
        return self._bbox


@responses.activate
def test_find_restaurants_parses_nodes_and_ways_and_skips_unnamed() -> None:
    settings = Settings()
    bbox = BoundingBox(south=45.7, north=45.8, west=4.8, east=4.9)
    geocoder = _StubGeocoder(bbox)

    responses.add(
        responses.POST,
        settings.overpass_base_url,
        json={
            "elements": [
                {
                    "type": "node",
                    "id": 1,
                    "lat": 45.75,
                    "lon": 4.85,
                    "tags": {
                        "name": "Le Petit Bistrot",
                        "amenity": "restaurant",
                        "addr:housenumber": "12",
                        "addr:street": "Rue de la République",
                        "addr:postcode": "69001",
                        "addr:city": "Lyon",
                    },
                },
                {
                    "type": "way",
                    "id": 2,
                    "center": {"lat": 45.76, "lon": 4.86},
                    "tags": {"name": "Café du Coin", "amenity": "cafe"},
                },
                {
                    "type": "node",
                    "id": 3,
                    "lat": 45.77,
                    "lon": 4.87,
                    "tags": {"amenity": "restaurant"},
                },
            ]
        },
        status=200,
    )

    source = OverpassRestaurantSource(
        session=requests.Session(), settings=settings, geocoder=geocoder
    )

    restaurants = source.find_restaurants("Lyon", categories=("restaurant", "cafe"))

    assert len(restaurants) == 2

    first = restaurants[0]
    assert first.name == "Le Petit Bistrot"
    assert first.category == "Restaurant"
    assert first.address == "12 Rue de la République, 69001"
    assert first.city == "Lyon"
    assert first.latitude == 45.75
    assert first.osm_id == "node/1"

    second = restaurants[1]
    assert second.name == "Café du Coin"
    assert second.category == "Café"
    assert second.latitude == 45.76  # provient du champ "center" (way)
    assert second.city == "Lyon"  # ville de repli, faute de tag addr:city


@responses.activate
def test_find_restaurants_returns_empty_list_when_nothing_found() -> None:
    settings = Settings()
    bbox = BoundingBox(south=0, north=0, west=0, east=0)
    geocoder = _StubGeocoder(bbox)

    responses.add(
        responses.POST, settings.overpass_base_url, json={"elements": []}, status=200
    )

    source = OverpassRestaurantSource(
        session=requests.Session(), settings=settings, geocoder=geocoder
    )

    assert source.find_restaurants("Nulle Part", categories=("restaurant",)) == []
