"""Tests de la classification de confiance Instagram (Élevé / Moyen / Faible)."""

from restaurant_finder.domain.models import InstagramConfidence
from restaurant_finder.enrichment.confidence import (
    classify_instagram_confidence,
    name_appears_in,
    strong_name_handle_match,
)


def test_name_appears_in_handles_accents_spaces_and_underscores() -> None:
    assert name_appears_in("Le Petit Bistrot", "lepetitbistrot")
    assert name_appears_in("Le Petit Bistrot", "le_petit_bistrot_off")
    assert name_appears_in("Café de l'Été", "cafe de l ete lyon")
    assert not name_appears_in("Le Petit Bistrot", "random_foodie_account")


def test_strong_match_examples_from_le_mans() -> None:
    assert strong_name_handle_match("Le Chemin de Table", "le.chemin.de.table")
    assert strong_name_handle_match("Thailand Food", "thailand_food")
    assert strong_name_handle_match("Le Comptoir des Papilles", "comptoirdespapilles")
    assert strong_name_handle_match("L'Himalaya", "restaurantlhimalaya")
    assert strong_name_handle_match("Le Galopin", "le.galopin")


def test_confidence_eleve_on_strong_handle_match_without_city() -> None:
    cases = [
        ("Le Chemin de Table", "le.chemin.de.table"),
        ("Thailand Food", "thailand_food"),
        ("Le Comptoir des Papilles", "comptoirdespapilles"),
        ("L'Himalaya", "restaurantlhimalaya"),
        ("Le Galopin", "le.galopin"),
    ]
    for name, handle in cases:
        assert (
            classify_instagram_confidence(name, "Le Mans", handle) == InstagramConfidence.ELEVE
        ), (name, handle)


def test_confidence_eleve_when_full_name_in_bio_even_without_handle_match() -> None:
    confidence = classify_instagram_confidence(
        "Le Petit Bistrot",
        "Lyon",
        "lpb_officiel",
        full_name="LPB",
        biography="Le Petit Bistrot — cuisine à Lyon",
    )
    assert confidence == InstagramConfidence.ELEVE


def test_confidence_eleve_when_name_in_handle_without_city_in_bio() -> None:
    confidence = classify_instagram_confidence(
        "Le Petit Bistrot",
        "Lyon",
        "lepetitbistrot",
        full_name="Le Petit Bistrot",
        biography="Cuisine traditionnelle",
    )
    assert confidence == InstagramConfidence.ELEVE


def test_confidence_moyen_on_partial_token_match() -> None:
    confidence = classify_instagram_confidence(
        "Le Petit Bistrot",
        "Lyon",
        "petitbistrot_off",
        full_name="",
        biography="",
    )
    assert confidence == InstagramConfidence.MOYEN


def test_confidence_eleve_when_city_upgrades_partial_match() -> None:
    confidence = classify_instagram_confidence(
        "Le Petit Bistrot",
        "Lyon",
        "petitbistrot_off",
        full_name="",
        biography="Ouvert tous les jours à Lyon",
    )
    assert confidence == InstagramConfidence.ELEVE


def test_confidence_faible_when_handle_prefix_suggests_other_place() -> None:
    confidence = classify_instagram_confidence(
        "Le Saint-Vincent",
        "Le Mans",
        "maisonsaintvincent",
    )
    assert confidence == InstagramConfidence.FAIBLE


def test_confidence_faible_when_no_clear_name_match() -> None:
    confidence = classify_instagram_confidence(
        "Le Petit Bistrot",
        "Lyon",
        "xyz_random_account",
        full_name="Voyages",
        biography="Blog photo Paris",
    )
    assert confidence == InstagramConfidence.FAIBLE
