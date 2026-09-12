"""Tests de la source de restaurants Overpass (OpenStreetMap)."""

from __future__ import annotations

import pytest
import requests
import responses

from restaurant_finder.config import Settings
from restaurant_finder.domain.models import BoundingBox
from restaurant_finder.exceptions import RestaurantSourceError
from restaurant_finder.geocoding.geo_math import PointQuery
from restaurant_finder.sources.overpass_source import OverpassRestaurantSource


class _StubGeocoder:
    """Remplace `NominatimGeocoder` pour isoler le test de la source Overpass."""

    def __init__(self, bbox: BoundingBox, reverse_label: str | None = None) -> None:
        self._bbox = bbox
        self._reverse_label = reverse_label

    def geocode_city(self, city: str) -> BoundingBox:
        return self._bbox

    def reverse_geocode_city(self, latitude: float, longitude: float) -> str | None:
        return self._reverse_label


@responses.activate
def test_find_restaurants_parses_nodes_and_ways_and_skips_unnamed() -> None:
    settings = Settings()
    bbox = BoundingBox(south=45.7, north=45.8, west=4.8, east=4.9)
    geocoder = _StubGeocoder(bbox)

    responses.add(
        responses.POST,
        settings.overpass_base_url,
        json={
            "osm3s": {"timestamp_osm_base": "2026-07-29T22:00:00Z"},
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
                        "cuisine": "bistro",
                        "contact:instagram": "https://www.instagram.com/lepetitbistrot/",
                        "website": "https://lepetitbistrot.fr/",
                    },
                },
                {
                    "type": "way",
                    "id": 2,
                    "center": {"lat": 45.76, "lon": 4.86},
                    "tags": {"name": "Café du Coin", "amenity": "cafe", "cuisine": "cafe"},
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
    assert first.instagram_url == "https://www.instagram.com/lepetitbistrot/"
    assert first.website == "https://lepetitbistrot.fr/"
    assert first.cuisine == "bistro"

    second = restaurants[1]
    assert second.name == "Café du Coin"
    assert second.category == "Café"
    assert second.latitude == 45.76  # provient du champ "center" (way)
    assert second.city == "Lyon"  # ville de repli, faute de tag addr:city
    assert second.cuisine == "cafe"

@responses.activate
def test_find_restaurants_returns_empty_list_when_nothing_found() -> None:
    settings = Settings()
    bbox = BoundingBox(south=0, north=0, west=0, east=0)
    geocoder = _StubGeocoder(bbox)

    responses.add(
        responses.POST,
        settings.overpass_base_url,
        json={"osm3s": {"timestamp_osm_base": "2026-07-29T22:00:00Z"}, "elements": []},
        status=200,
    )

    source = OverpassRestaurantSource(
        session=requests.Session(), settings=settings, geocoder=geocoder
    )

    assert source.find_restaurants("Nulle Part", categories=("restaurant",)) == []


@responses.activate
def test_find_restaurants_falls_back_to_next_mirror_on_error() -> None:
    settings = Settings(
        overpass_base_url="https://mirror-a.example/api/interpreter",
        overpass_fallback_urls=("https://mirror-b.example/api/interpreter",),
        overpass_busy_retry_seconds=0,
    )
    bbox = BoundingBox(south=45.7, north=45.8, west=4.8, east=4.9)
    geocoder = _StubGeocoder(bbox)

    responses.add(responses.POST, settings.overpass_base_url, status=406)
    responses.add(responses.POST, settings.overpass_base_url, status=406)
    responses.add(
        responses.POST,
        settings.overpass_fallback_urls[0],
        json={
            "osm3s": {"timestamp_osm_base": "2026-07-29T22:00:00Z"},
            "elements": [
                {
                    "type": "node",
                    "id": 10,
                    "lat": 45.75,
                    "lon": 4.85,
                    "tags": {"name": "Fallback Bistro", "amenity": "restaurant"},
                }
            ]
        },
        status=200,
    )

    source = OverpassRestaurantSource(
        session=requests.Session(), settings=settings, geocoder=geocoder
    )

    restaurants = source.find_restaurants("Lyon", categories=("restaurant",))
    assert len(restaurants) == 1
    assert restaurants[0].name == "Fallback Bistro"


@responses.activate
def test_find_restaurants_rejects_mirror_with_invalid_osm_timestamp() -> None:
    settings = Settings(
        overpass_base_url="https://mirror-broken.example/api/interpreter",
        overpass_fallback_urls=("https://mirror-ok.example/api/interpreter",),
        overpass_busy_retry_seconds=0,
    )
    bbox = BoundingBox(south=45.7, north=45.8, west=4.8, east=4.9)
    geocoder = _StubGeocoder(bbox)

    responses.add(
        responses.POST,
        settings.overpass_base_url,
        json={"osm3s": {"timestamp_osm_base": "116016"}, "elements": []},
        status=200,
    )
    responses.add(
        responses.POST,
        settings.overpass_fallback_urls[0],
        json={
            "osm3s": {"timestamp_osm_base": "2026-07-29T22:00:00Z"},
            "elements": [
                {
                    "type": "node",
                    "id": 11,
                    "lat": 45.75,
                    "lon": 4.85,
                    "tags": {"name": "Valid Mirror", "amenity": "restaurant"},
                }
            ],
        },
        status=200,
    )

    source = OverpassRestaurantSource(
        session=requests.Session(), settings=settings, geocoder=geocoder
    )

    restaurants = source.find_restaurants("Lyon", categories=("restaurant",))
    assert restaurants[0].name == "Valid Mirror"


@responses.activate
def test_find_restaurants_near_points_uses_reverse_geocoded_label() -> None:
    settings = Settings(overpass_rate_limit_seconds=0)
    geocoder = _StubGeocoder(BoundingBox(south=0, north=0, west=0, east=0), reverse_label="Nice")

    responses.add(
        responses.POST,
        settings.overpass_base_url,
        json={
            "osm3s": {"timestamp_osm_base": "2026-07-29T22:00:00Z"},
            "elements": [
                {
                    "type": "node",
                    "id": 1,
                    "lat": 43.700,
                    "lon": 7.268,
                    "tags": {"name": "Le Safari", "amenity": "restaurant"},
                }
            ],
        },
        status=200,
    )

    source = OverpassRestaurantSource(
        session=requests.Session(), settings=settings, geocoder=geocoder
    )

    restaurants = source.find_restaurants_near_points(
        points=[PointQuery(43.700, 7.268, 500)], categories=("restaurant",)
    )

    assert len(restaurants) == 1
    assert restaurants[0].city == "Nice"


@responses.activate
def test_find_restaurants_near_points_filters_out_of_radius_results() -> None:
    settings = Settings(overpass_rate_limit_seconds=0)
    geocoder = _StubGeocoder(BoundingBox(south=0, north=0, west=0, east=0))

    responses.add(
        responses.POST,
        settings.overpass_base_url,
        json={
            "osm3s": {"timestamp_osm_base": "2026-07-29T22:00:00Z"},
            "elements": [
                {
                    "type": "node",
                    "id": 1,
                    "lat": 43.700,
                    "lon": 7.268,
                    "tags": {"name": "Tout près", "amenity": "restaurant"},
                },
                {
                    "type": "node",
                    "id": 2,
                    # ~5.5km plus loin : hors du rayon demandé.
                    "lat": 43.750,
                    "lon": 7.268,
                    "tags": {"name": "Trop loin", "amenity": "restaurant"},
                },
            ],
        },
        status=200,
    )

    source = OverpassRestaurantSource(
        session=requests.Session(), settings=settings, geocoder=geocoder
    )

    restaurants = source.find_restaurants_near_points(
        points=[PointQuery(43.700, 7.268, 500)], categories=("restaurant",)
    )

    assert [r.name for r in restaurants] == ["Tout près"]


@responses.activate
def test_find_restaurants_near_points_deduplicates_overlapping_points() -> None:
    settings = Settings(overpass_rate_limit_seconds=0)
    geocoder = _StubGeocoder(BoundingBox(south=0, north=0, west=0, east=0))

    shared_element = {
        "type": "node",
        "id": 1,
        "lat": 43.700,
        "lon": 7.268,
        "tags": {"name": "Le Safari", "amenity": "restaurant"},
    }
    responses.add(
        responses.POST,
        settings.overpass_base_url,
        json={
            "osm3s": {"timestamp_osm_base": "2026-07-29T22:00:00Z"},
            "elements": [shared_element],
        },
        status=200,
    )
    responses.add(
        responses.POST,
        settings.overpass_base_url,
        json={
            "osm3s": {"timestamp_osm_base": "2026-07-29T22:00:00Z"},
            "elements": [shared_element],
        },
        status=200,
    )

    source = OverpassRestaurantSource(
        session=requests.Session(), settings=settings, geocoder=geocoder
    )

    restaurants = source.find_restaurants_near_points(
        points=[PointQuery(43.700, 7.268, 500), PointQuery(43.7005, 7.2685, 500)],
        categories=("restaurant",),
    )

    assert len(restaurants) == 1


@responses.activate
def test_find_restaurants_retries_on_transient_connection_error_then_succeeds() -> None:
    settings = Settings(retry_base_delay_seconds=0, retry_max_attempts=2)
    bbox = BoundingBox(south=45.7, north=45.8, west=4.8, east=4.9)
    geocoder = _StubGeocoder(bbox)

    responses.add(
        responses.POST, settings.overpass_base_url, body=requests.exceptions.ConnectionError()
    )
    responses.add(
        responses.POST,
        settings.overpass_base_url,
        json={
            "osm3s": {"timestamp_osm_base": "2026-07-29T22:00:00Z"},
            "elements": [
                {
                    "type": "node",
                    "id": 1,
                    "lat": 45.75,
                    "lon": 4.85,
                    "tags": {"name": "Résilient", "amenity": "restaurant"},
                }
            ],
        },
        status=200,
    )

    source = OverpassRestaurantSource(
        session=requests.Session(), settings=settings, geocoder=geocoder
    )

    restaurants = source.find_restaurants("Lyon", categories=("restaurant",))

    assert [r.name for r in restaurants] == ["Résilient"]
    assert len(responses.calls) == 2


@responses.activate
def test_find_restaurants_raises_after_persistent_connection_errors_on_all_mirrors() -> None:
    settings = Settings(
        overpass_fallback_urls=("https://mirror-b.example/api/interpreter",),
        retry_base_delay_seconds=0,
        retry_max_attempts=2,
    )
    bbox = BoundingBox(south=45.7, north=45.8, west=4.8, east=4.9)
    geocoder = _StubGeocoder(bbox)

    for endpoint in (settings.overpass_base_url, *settings.overpass_fallback_urls):
        for _ in range(2):
            responses.add(
                responses.POST, endpoint, body=requests.exceptions.ConnectionError()
            )

    source = OverpassRestaurantSource(
        session=requests.Session(), settings=settings, geocoder=geocoder
    )

    with pytest.raises(RestaurantSourceError):
        source.find_restaurants("Lyon", categories=("restaurant",))


@responses.activate
def test_find_restaurants_near_points_skips_failing_point_and_keeps_others() -> None:
    settings = Settings(
        overpass_fallback_urls=(),
        overpass_busy_retry_seconds=0,
        overpass_rate_limit_seconds=0,
    )
    geocoder = _StubGeocoder(BoundingBox(south=0, north=0, west=0, east=0))

    # Point 1 : le miroir unique sature sur ses deux tentatives -> échec du point.
    responses.add(responses.POST, settings.overpass_base_url, status=406)
    responses.add(responses.POST, settings.overpass_base_url, status=406)
    # Point 2 : réussit normalement.
    responses.add(
        responses.POST,
        settings.overpass_base_url,
        json={
            "osm3s": {"timestamp_osm_base": "2026-07-29T22:00:00Z"},
            "elements": [
                {
                    "type": "node",
                    "id": 2,
                    "lat": 44.0,
                    "lon": 7.0,
                    "tags": {"name": "Le Safari", "amenity": "restaurant"},
                }
            ],
        },
        status=200,
    )

    source = OverpassRestaurantSource(
        session=requests.Session(), settings=settings, geocoder=geocoder
    )

    restaurants = source.find_restaurants_near_points(
        points=[PointQuery(43.7, 7.27, 500), PointQuery(44.0, 7.0, 500)],
        categories=("restaurant",),
    )

    assert [r.name for r in restaurants] == ["Le Safari"]


@responses.activate
def test_find_restaurants_near_points_raises_when_every_point_fails() -> None:
    settings = Settings(
        overpass_fallback_urls=(),
        overpass_busy_retry_seconds=0,
        overpass_rate_limit_seconds=0,
    )
    geocoder = _StubGeocoder(BoundingBox(south=0, north=0, west=0, east=0))

    for _ in range(4):  # 2 points x 2 tentatives de saturation chacun.
        responses.add(responses.POST, settings.overpass_base_url, status=406)

    source = OverpassRestaurantSource(
        session=requests.Session(), settings=settings, geocoder=geocoder
    )

    with pytest.raises(RestaurantSourceError):
        source.find_restaurants_near_points(
            points=[PointQuery(43.7, 7.27, 500), PointQuery(44.0, 7.0, 500)],
            categories=("restaurant",),
        )
