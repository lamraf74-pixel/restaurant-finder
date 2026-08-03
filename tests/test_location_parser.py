"""Tests du parseur de localisation (coordonnées / liens Google Maps)."""

from __future__ import annotations

import pytest
import requests
import responses

from restaurant_finder.config import Settings
from restaurant_finder.exceptions import LocationParsingError
from restaurant_finder.geocoding.location_parser import LocationInputParser


def _parser() -> LocationInputParser:
    return LocationInputParser(session=requests.Session(), settings=Settings())


def test_parses_plain_coordinates() -> None:
    assert _parser().parse("45.917707, 6.131942") == (45.917707, 6.131942)


def test_parses_plain_coordinates_without_space() -> None:
    assert _parser().parse("45.917707,6.131942") == (45.917707, 6.131942)


def test_parses_negative_coordinates() -> None:
    assert _parser().parse("-33.8688, 151.2093") == (-33.8688, 151.2093)


def test_parses_google_maps_at_url() -> None:
    url = "https://www.google.com/maps/place/Le+Safari/@43.6952,7.2716,17z/data=..."
    assert _parser().parse(url) == (43.6952, 7.2716)


def test_parses_google_maps_query_param() -> None:
    url = "https://www.google.com/maps?q=48.8566,2.3522"
    assert _parser().parse(url) == (48.8566, 2.3522)


def test_parses_google_maps_ll_param() -> None:
    url = "https://maps.google.com/maps?ll=48.8566,2.3522&z=15"
    assert _parser().parse(url) == (48.8566, 2.3522)


def test_raises_on_unparseable_input() -> None:
    with pytest.raises(LocationParsingError):
        _parser().parse("Nice")


def test_raises_on_out_of_range_coordinates() -> None:
    with pytest.raises(LocationParsingError):
        _parser().parse("200.0, 6.0")


@responses.activate
def test_resolves_short_link_redirect() -> None:
    short_url = "https://maps.app.goo.gl/AbCdEf"
    resolved_url = "https://www.google.com/maps/place/@45.9,6.1,15z"
    responses.add(
        responses.GET,
        short_url,
        status=302,
        headers={"Location": resolved_url},
    )
    responses.add(responses.GET, resolved_url, status=200, body="ok")

    parser = LocationInputParser(session=requests.Session(), settings=Settings())
    assert parser.parse(short_url) == (45.9, 6.1)
