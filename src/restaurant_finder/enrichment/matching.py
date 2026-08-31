"""Logique de matching flou entre un nom de restaurant et un résultat web.

Isolée dans son propre module car c'est la partie la plus "heuristique"
du projet : elle est testée unitairement en isolation, indépendamment
du réseau.
"""

from __future__ import annotations

from rapidfuzz import fuzz

from restaurant_finder.utils.text import normalize_text

#: En dessous de cette longueur (caractères, sans espaces), un nom est trop
#: générique ("Le Bar", "Chez Toi") pour qu'un score élevé soit fiable :
#: n'importe quel texte contenant ces mots matcherait à tort.
_SHORT_NAME_LENGTH = 8
_SHORT_NAME_PENALTY = 0.7


def score_candidate(restaurant_name: str, candidate_text: str) -> int:
    """Retourne un score de similarité (0-100) entre un restaurant et un texte.

    Combine deux métriques rapidfuzz robustes aux mots supplémentaires ou
    réordonnés (ex: "Le Petit Café" vs "Le Petit Café officiel · Instagram
    photos and videos"). `partial_ratio` est volontairement évité : il fait
    correspondre n'importe quelle sous-chaîne, ce qui génère énormément de
    faux positifs sur les noms courts ou génériques.
    """

    normalized_name = normalize_text(restaurant_name)
    normalized_candidate = normalize_text(candidate_text)

    if not normalized_name or not normalized_candidate:
        return 0

    token_sort_score = fuzz.token_sort_ratio(normalized_name, normalized_candidate)
    token_set_score = fuzz.token_set_ratio(normalized_name, normalized_candidate)
    score = max(token_sort_score, token_set_score)

    name_length = len(normalized_name.replace(" ", ""))
    if name_length < _SHORT_NAME_LENGTH:
        score *= _SHORT_NAME_PENALTY

    return round(score)
