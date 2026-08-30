"""Tests de la classification de confiance Instagram (Élevé / Moyen / Faible)."""

from restaurant_finder.domain.models import InstagramConfidence
from restaurant_finder.enrichment.confidence import (
    classify_instagram_confidence,
    name_appears_in,
)


def test_name_appears_in_handles_accents_spaces_and_underscores() -> None:
    assert name_appears_in("Le Petit Bistrot", "lepetitbistrot")
    assert name_appears_in("Le Petit Bistrot", "le_petit_bistrot_off")
    assert name_appears_in("Café de l'Été", "cafe de l ete lyon")
    assert not name_appears_in("Le Petit Bistrot", "random_foodie_account")


def test_confidence_eleve_when_name_and_city_in_bio() -> None:
    confidence = classify_instagram_confidence(
        "Le Petit Bistrot",
        "Lyon",
        "lpb_officiel",
        full_name="LPB",
        biography="Le Petit Bistrot — cuisine à Lyon",
    )
    assert confidence == InstagramConfidence.ELEVE


def test_confidence_eleve_when_name_in_handle_and_city_in_bio() -> None:
    confidence = classify_instagram_confidence(
        "Le Petit Bistrot",
        "Lyon",
        "lepetitbistrot",
        full_name="",
        biography="Ouvert tous les jours à Lyon",
    )
    assert confidence == InstagramConfidence.ELEVE


def test_confidence_moyen_when_name_matched_but_city_not_in_bio() -> None:
    confidence = classify_instagram_confidence(
        "Le Petit Bistrot",
        "Lyon",
        "lepetitbistrot",
        full_name="Le Petit Bistrot",
        biography="Cuisine traditionnelle",
    )
    assert confidence == InstagramConfidence.MOYEN


def test_confidence_faible_when_no_clear_name_match() -> None:
    confidence = classify_instagram_confidence(
        "Le Petit Bistrot",
        "Lyon",
        "xyz_random_account",
        full_name="Voyages",
        biography="Blog photo Paris",
    )
    assert confidence == InstagramConfidence.FAIBLE
