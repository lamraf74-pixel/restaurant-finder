"""Logique de matching flou entre un nom de restaurant et un résultat web.

Isolée dans son propre module car c'est la partie la plus "heuristique"
du projet : elle est testée unitairement en isolation, indépendamment
du réseau.
"""

from __future__ import annotations

from rapidfuzz import fuzz

from restaurant_finder.utils.text import normalize_text


def score_candidate(restaurant_name: str, candidate_text: str) -> int:
    """Retourne un score de similarité (0-100) entre un restaurant et un texte.

    Combine deux métriques rapidfuzz pour être robuste à la fois aux
    réordonnancements de mots et aux textes partiels (ex: "Le Petit Café"
    vs "lepetitcafe_officiel · Instagram").
    """

    normalized_name = normalize_text(restaurant_name)
    normalized_candidate = normalize_text(candidate_text)

    if not normalized_name or not normalized_candidate:
        return 0

    token_score = fuzz.token_sort_ratio(normalized_name, normalized_candidate)
    partial_score = fuzz.partial_ratio(normalized_name, normalized_candidate)

    return round(max(token_score, partial_score))
