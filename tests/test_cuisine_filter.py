"""Tests du filtre sur le tag OSM `cuisine`."""

from restaurant_finder.domain.models import Restaurant
from restaurant_finder.filtering.cuisine_filter import (
    DEFAULT_CUISINES,
    CuisineFilter,
    parse_cuisine_values,
)


def _restaurant(name: str, cuisine: str | None = None) -> Restaurant:
    return Restaurant(
        osm_id="node/1",
        name=name,
        category="Restaurant",
        city="Nice",
        cuisine=cuisine,
    )


def test_default_cuisines_list_is_documentation_only() -> None:
    assert DEFAULT_CUISINES == ("bistro", "pizza", "sandwich", "cafe", "brunch")


def test_parse_cuisine_values_returns_none_when_empty() -> None:
    assert parse_cuisine_values(None) is None
    assert parse_cuisine_values("") is None
    assert parse_cuisine_values("  ") is None


def test_parse_cuisine_values_custom_list() -> None:
    assert parse_cuisine_values("italian, sushi") == ("italian", "sushi")


def test_keeps_matching_cuisine_and_excludes_others() -> None:
    filt = CuisineFilter(("pizza", "bistro"))
    restaurants = [
        _restaurant("Pizzeria", "pizza"),
        _restaurant("Sushi", "sushi"),
        _restaurant("Bistrot", "bistro;french"),
        _restaurant("Sans tag"),
    ]
    kept, excluded = filt.apply(restaurants)
    assert [item.name for item in kept] == ["Pizzeria", "Bistrot"]
    assert excluded == 2


def test_excludes_restaurants_without_cuisine_tag() -> None:
    filt = CuisineFilter(("cafe",))
    assert not filt.matches(_restaurant("Chez André"))
    assert filt.matches(_restaurant("Café", "cafe"))
