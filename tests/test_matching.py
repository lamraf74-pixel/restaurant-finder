"""Tests de la normalisation de texte et du matching flou."""

from restaurant_finder.enrichment.matching import score_candidate
from restaurant_finder.utils.text import normalize_text


def test_normalize_text_strips_accents_and_punctuation() -> None:
    assert normalize_text("Café de l'Été !") == "cafe de l ete"


def test_normalize_text_collapses_whitespace() -> None:
    assert normalize_text("  Le   Petit   Bistrot ") == "le petit bistrot"


def test_score_candidate_exact_match_is_maximal() -> None:
    assert score_candidate("Le Petit Bistrot", "Le Petit Bistrot") == 100


def test_score_candidate_handle_style_text_scores_high() -> None:
    score = score_candidate(
        "Le Petit Bistrot", "Le Petit Bistrot (@lepetitbistrot_officiel) Instagram"
    )
    assert score >= 60


def test_score_candidate_unrelated_text_scores_low() -> None:
    score = score_candidate("Le Petit Bistrot", "Pharmacie du Centre")
    assert score < 60


def test_score_candidate_empty_strings_returns_zero() -> None:
    assert score_candidate("", "Le Petit Bistrot") == 0
    assert score_candidate("Le Petit Bistrot", "") == 0


def test_score_candidate_extra_words_still_scores_high() -> None:
    """token_set_ratio doit rester robuste aux mots ajoutés (titre de résultat web)."""

    score = score_candidate(
        "Le Petit Bistrot",
        "Le Petit Bistrot (@lepetitbistrot_officiel) • Instagram photos and videos",
    )
    assert score >= 85


def test_score_candidate_short_generic_name_is_penalized() -> None:
    """Un nom très court/générique ne doit pas matcher n'importe quel texte
    qui le contient par coïncidence (source historique de faux positifs)."""

    unrelated_score = score_candidate("Le Bar", "Ambiance cocktails au bar de la marina, Cannes")
    exact_score = score_candidate("Le Bar", "Le Bar")

    assert exact_score >= 60
    assert unrelated_score < exact_score
    assert unrelated_score < 55
