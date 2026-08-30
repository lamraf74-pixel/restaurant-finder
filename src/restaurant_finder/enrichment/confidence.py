"""Classification du niveau de confiance d'une association Instagram.

Trois niveaux explicites (indépendants du score rapidfuzz numérique) :

- **Élevé** : le nom du restaurant (ou une variante proche) apparaît dans le
  handle / nom affiché / bio, **et** la ville apparaît dans la bio.
- **Moyen** : le nom apparaît, mais la ville n'est pas confirmable dans la bio.
- **Faible** : aucune correspondance claire du nom — association incertaine.
"""

from __future__ import annotations

from restaurant_finder.domain.models import InstagramConfidence
from restaurant_finder.utils.text import compact_text, normalize_text

#: En dessous de cette longueur compacte, un nom est trop générique pour
#: une présence littérale fiable ("bar", "cafe"...).
_MIN_NAME_COMPACT_LENGTH = 4


def name_appears_in(restaurant_name: str, *texts: str) -> bool:
    """True si le nom (normalisé ou compact) apparaît dans l'un des textes."""

    normalized_name = normalize_text(restaurant_name)
    compact_name = compact_text(restaurant_name)
    if not compact_name or len(compact_name) < _MIN_NAME_COMPACT_LENGTH:
        return False

    for text in texts:
        if not text:
            continue
        normalized_haystack = normalize_text(text)
        compact_haystack = compact_text(text)
        if normalized_name and normalized_name in normalized_haystack:
            return True
        if compact_name in compact_haystack:
            return True
    return False


def city_appears_in_bio(city: str, biography: str) -> bool:
    """True si la ville (token compact) apparaît dans la biographie."""

    city_token = compact_text(city)
    if not city_token:
        return False
    return city_token in compact_text(biography)


def classify_instagram_confidence(
    restaurant_name: str,
    city: str,
    handle: str,
    full_name: str = "",
    biography: str = "",
) -> InstagramConfidence:
    """Classe une association Instagram selon les règles métier Élevé/Moyen/Faible."""

    handle_readable = handle.replace(".", " ").replace("_", " ")
    name_matched = name_appears_in(restaurant_name, handle_readable, full_name, biography)
    if not name_matched:
        return InstagramConfidence.FAIBLE

    city_known = bool(compact_text(city))
    if not city_known:
        # Pas de ville à confirmer : le match sur le nom suffit pour Élevé.
        return InstagramConfidence.ELEVE

    if biography and city_appears_in_bio(city, biography):
        return InstagramConfidence.ELEVE

    return InstagramConfidence.MOYEN
