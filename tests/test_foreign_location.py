"""Tests du signal de localisation hors de France dans une bio Instagram."""

from restaurant_finder.enrichment.foreign_location import location_suggests_foreign_country


def test_empty_or_french_bio_is_not_foreign() -> None:
    assert not location_suggests_foreign_country("")
    assert not location_suggests_foreign_country("Cuisine traditionnelle, ouvert 7j/7")
    assert not location_suggests_foreign_country(
        "Réservations +33 4 78 00 00 00 — Lyon", restaurant_city="Lyon"
    )
    assert not location_suggests_foreign_country("Restaurant français 🇫🇷 Paris")


def test_spanish_phone_and_city_are_foreign() -> None:
    assert location_suggests_foreign_country(
        "Restaurante en Barcelona +34 932 000 000", restaurant_city="Lyon"
    )
    assert location_suggests_foreign_country("Madrid, España")
    assert location_suggests_foreign_country("📍 Barcelona 🇪🇸")


def test_italian_and_portuguese_signals_are_foreign() -> None:
    assert location_suggests_foreign_country("Trattoria a Roma 🇮🇹")
    assert location_suggests_foreign_country("Lisboa • +351 21 000 0000")
    assert location_suggests_foreign_country("00 39 06 1234 5678")


def test_overseas_french_phone_is_not_foreign() -> None:
    assert not location_suggests_foreign_country("Guadeloupe +590 590 00 00 00")
    assert not location_suggests_foreign_country("Réunion +262 262 00 00 00")


def test_cuisine_origin_is_not_a_location() -> None:
    assert not location_suggests_foreign_country(
        "Spécialités d'Espagne et tapas", restaurant_city="Lyon"
    )
    assert not location_suggests_foreign_country(
        "Cuisine italienne maison", restaurant_name="Le Petit Bistrot"
    )


def test_french_city_in_bio_neutralizes_nearby_foreign_city() -> None:
    """Bistrot à Perpignan qui cite Barcelone : toujours en France."""

    assert not location_suggests_foreign_country(
        "À 30 min de Barcelone 📍 Perpignan", restaurant_city="Perpignan"
    )


def test_country_in_restaurant_name_is_not_a_foreign_signal() -> None:
    """« Thailand Food » / handle thailand_food ne doit pas être pénalisé."""

    assert not location_suggests_foreign_country(
        "thailand_food",
        restaurant_city="Le Mans",
        restaurant_name="Thailand Food",
    )


def test_bangkok_bio_is_foreign_even_if_name_contains_thailand() -> None:
    assert location_suggests_foreign_country(
        "Bangkok 🇹🇭 street food",
        restaurant_city="Le Mans",
        restaurant_name="Thailand Food",
    )
