"""Tests du client de géocodage Nominatim."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
import requests
import responses

from restaurant_finder.config import Settings
from restaurant_finder.exceptions import GeocodingError
from restaurant_finder.geocoding.nominatim_client import NominatimGeocoder


@responses.activate
def test_geocode_city_returns_bounding_box() -> None:
    settings = Settings(nominatim_rate_limit_seconds=0)
    responses.add(
        responses.GET,
        f"{settings.nominatim_base_url}/search",
        json=[{"boundingbox": ["45.7", "45.8", "4.8", "4.9"]}],
        status=200,
    )

    geocoder = NominatimGeocoder(session=requests.Session(), settings=settings)
    bbox = geocoder.geocode_city("Lyon")

    assert bbox.south == 45.7
    assert bbox.north == 45.8
    assert bbox.west == 4.8
    assert bbox.east == 4.9

    query = parse_qs(urlparse(responses.calls[0].request.url).query)
    assert query.get("countrycodes") == ["fr"]
    assert query.get("city") == ["Lyon"]


@responses.activate
def test_geocode_city_restricts_search_to_france() -> None:
    """Les homonymes étrangers (Paris TX, Lyon BE) sont exclus via countrycodes=fr."""

    settings = Settings(nominatim_rate_limit_seconds=0)
    responses.add(
        responses.GET,
        f"{settings.nominatim_base_url}/search",
        json=[{"boundingbox": ["48.8", "48.9", "2.2", "2.5"]}],
        status=200,
    )

    geocoder = NominatimGeocoder(session=requests.Session(), settings=settings)
    geocoder.geocode_city("Paris")

    query = parse_qs(urlparse(responses.calls[0].request.url).query)
    assert query["countrycodes"] == ["fr"]
    assert query["format"] == ["jsonv2"]
    assert query["limit"] == ["1"]


@responses.activate
def test_geocode_city_raises_when_not_found() -> None:
    settings = Settings(nominatim_rate_limit_seconds=0)
    responses.add(
        responses.GET, f"{settings.nominatim_base_url}/search", json=[], status=200
    )

    geocoder = NominatimGeocoder(session=requests.Session(), settings=settings)

    with pytest.raises(GeocodingError):
        geocoder.geocode_city("Ville Inexistante")


@responses.activate
def test_geocode_city_uses_cache_and_avoids_second_request() -> None:
    settings = Settings(nominatim_rate_limit_seconds=0)
    responses.add(
        responses.GET,
        f"{settings.nominatim_base_url}/search",
        json=[{"boundingbox": ["45.7", "45.8", "4.8", "4.9"]}],
        status=200,
    )

    class _FakeCache:
        def __init__(self) -> None:
            self.store: dict[str, object] = {}

        def get(self, key: str) -> object | None:
            return self.store.get(key)

        def set(self, key: str, value: object) -> None:
            self.store[key] = value

    cache = _FakeCache()
    geocoder = NominatimGeocoder(session=requests.Session(), settings=settings, cache=cache)

    geocoder.geocode_city("Lyon")
    geocoder.geocode_city("Lyon")

    assert len(responses.calls) == 1


@responses.activate
def test_reverse_geocode_city_returns_locality_name() -> None:
    settings = Settings(nominatim_rate_limit_seconds=0)
    responses.add(
        responses.GET,
        f"{settings.nominatim_base_url}/reverse",
        json={"address": {"city": "Nice", "country": "France"}},
        status=200,
    )

    geocoder = NominatimGeocoder(session=requests.Session(), settings=settings)
    assert geocoder.reverse_geocode_city(43.7, 7.25) == "Nice"


@responses.activate
def test_reverse_geocode_city_returns_none_when_unavailable() -> None:
    settings = Settings(nominatim_rate_limit_seconds=0)
    responses.add(
        responses.GET, f"{settings.nominatim_base_url}/reverse", status=500
    )

    geocoder = NominatimGeocoder(session=requests.Session(), settings=settings)
    assert geocoder.reverse_geocode_city(43.7, 7.25) is None


@responses.activate
def test_geocode_city_retries_on_transient_connection_error_then_succeeds() -> None:
    settings = Settings(nominatim_rate_limit_seconds=0, retry_base_delay_seconds=0)
    responses.add(
        responses.GET,
        f"{settings.nominatim_base_url}/search",
        body=requests.exceptions.ConnectionError(),
    )
    responses.add(
        responses.GET,
        f"{settings.nominatim_base_url}/search",
        json=[{"boundingbox": ["45.7", "45.8", "4.8", "4.9"]}],
        status=200,
    )

    geocoder = NominatimGeocoder(session=requests.Session(), settings=settings)
    bbox = geocoder.geocode_city("Lyon")

    assert bbox.south == 45.7
    assert len(responses.calls) == 2


@responses.activate
def test_geocode_city_raises_geocoding_error_after_persistent_connection_errors() -> None:
    settings = Settings(
        nominatim_rate_limit_seconds=0, retry_base_delay_seconds=0, retry_max_attempts=2
    )
    for _ in range(2):
        responses.add(
            responses.GET,
            f"{settings.nominatim_base_url}/search",
            body=requests.exceptions.ConnectionError(),
        )

    geocoder = NominatimGeocoder(session=requests.Session(), settings=settings)

    with pytest.raises(GeocodingError):
        geocoder.geocode_city("Lyon")

    assert len(responses.calls) == 2
