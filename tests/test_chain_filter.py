"""Tests du filtre d'enseignes / franchises."""

from restaurant_finder.domain.models import Restaurant
from restaurant_finder.filtering.chain_filter import ChainRestaurantFilter


def _restaurant(name: str, brand: str | None = None, operator: str | None = None) -> Restaurant:
    return Restaurant(
        osm_id="node/1",
        name=name,
        category="Restaurant",
        city="Nice",
        brand=brand,
        operator=operator,
    )


def test_detects_mcdonalds_variants() -> None:
    filt = ChainRestaurantFilter()
    assert filt.is_chain(_restaurant("McDonald's"))
    assert filt.is_chain(_restaurant("McDo Nice Centre"))
    assert filt.is_chain(_restaurant("Restaurant Local", brand="McDonald's"))


def test_detects_subway_burger_king() -> None:
    filt = ChainRestaurantFilter()
    assert filt.is_chain(_restaurant("Subway"))
    assert filt.is_chain(_restaurant("Burger King Promenade"))


def test_keeps_independent_bistro() -> None:
    filt = ChainRestaurantFilter()
    assert not filt.is_chain(_restaurant("Le Petit Bistrot"))
    assert not filt.is_chain(_restaurant("Chez André"))
    assert not filt.is_chain(_restaurant("La Voglia"))


def test_exclude_chains_returns_only_independents() -> None:
    filt = ChainRestaurantFilter()
    restaurants = [
        _restaurant("Le Petit Bistrot"),
        _restaurant("McDonald's"),
        _restaurant("La Maison Libanaise"),
        _restaurant("Subway Gare"),
    ]
    kept, excluded = filt.exclude_chains(restaurants)
    assert excluded == 2
    assert [item.name for item in kept] == ["Le Petit Bistrot", "La Maison Libanaise"]
