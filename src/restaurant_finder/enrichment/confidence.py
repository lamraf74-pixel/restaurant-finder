"""Classification du niveau de confiance d'une association Instagram.

Trois niveaux (indépendants du score rapidfuzz numérique) :

- **Élevé** : correspondance forte entre le nom compacté du restaurant et le
  handle (égalité, ou l'un contenu dans l'autre). La ville n'est plus
  obligatoire ; si elle est confirmée, elle peut aussi faire monter un Moyen.
- **Moyen** : overlap partiel plausible (mots significatifs du nom dans le
  handle), sans contenance complète.
- **Faible** : pas de correspondance claire, ou résidu de handle qui suggère
  un autre établissement (ex. préfixe ``maison`` vs ``le``).
"""

from __future__ import annotations

from restaurant_finder.domain.models import InstagramConfidence
from restaurant_finder.utils.text import compact_text, normalize_text

#: En dessous de cette longueur compacte, un nom est trop générique.
_MIN_NAME_COMPACT_LENGTH = 4

_STOPWORDS = frozenset(
    {
        "le",
        "la",
        "les",
        "l",
        "de",
        "du",
        "des",
        "et",
        "au",
        "aux",
        "un",
        "une",
        "a",
        "the",
        "and",
        "of",
        "at",
    }
)

#: Suffixes / décorations courantes sur les handles, à ignorer pour le résidu.
_DECORATIVE_HANDLE_PARTS = frozenset(
    {
        "off",
        "officiel",
        "official",
        "resto",
        "restaurant",
        "cafe",
        "bar",
        "food",
        "insta",
        "ig",
    }
)

#: Préfixes qui, s'ils restent après retrait du nom, suggèrent un autre lieu.
_CONFLICT_HANDLE_PREFIXES = frozenset(
    {
        "maison",
        "hotel",
        "auberge",
        "chateau",
        "villa",
        "domaine",
        "brasserie",
        "bistro",
        "bistrot",
    }
)


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


def _significant_tokens(name: str) -> list[str]:
    return [
        token
        for token in normalize_text(name).split()
        if token not in _STOPWORDS and len(token) >= 3
    ]


def strong_name_handle_match(restaurant_name: str, handle_or_text: str) -> bool:
    """Correspondance forte nom ↔ texte (égalité ou contenance compacte)."""

    compact_name = compact_text(restaurant_name)
    compact_other = compact_text(handle_or_text)
    if not compact_name or len(compact_name) < _MIN_NAME_COMPACT_LENGTH:
        return False
    if not compact_other:
        return False
    return (
        compact_name == compact_other
        or compact_name in compact_other
        or compact_other in compact_name
    )


def _partial_token_match(restaurant_name: str, handle: str) -> bool:
    """Overlap partiel : assez de mots significatifs du nom présents dans le handle."""

    compact_handle = compact_text(handle)
    tokens = _significant_tokens(restaurant_name)
    if not tokens or not compact_handle:
        return False

    matched = [token for token in tokens if token in compact_handle]
    if not matched:
        return False
    if len(tokens) == 1:
        return len(matched[0]) >= 5
    return len(matched) >= max(2, (len(tokens) + 1) // 2)


def _handle_suggests_different_place(restaurant_name: str, handle: str) -> bool:
    """True si un résidu de handle (ex. ``maison``) suggère un autre établissement."""

    remaining = compact_text(handle)
    if not remaining:
        return False

    for token in sorted(_significant_tokens(restaurant_name), key=len, reverse=True):
        remaining = remaining.replace(token, "", 1)

    for deco in sorted(_DECORATIVE_HANDLE_PARTS, key=len, reverse=True):
        remaining = remaining.replace(deco, "")

    for article in ("les", "le", "la", "l"):
        if remaining.startswith(article):
            remaining = remaining[len(article) :]

    if len(remaining) < 4:
        return False

    for conflict in _CONFLICT_HANDLE_PREFIXES:
        if remaining == conflict or remaining.startswith(conflict):
            return True
    return False


def classify_instagram_confidence(
    restaurant_name: str,
    city: str,
    handle: str,
    full_name: str = "",
    biography: str = "",
) -> InstagramConfidence:
    """Classe une association Instagram selon les règles métier Élevé/Moyen/Faible."""

    if strong_name_handle_match(restaurant_name, handle):
        return InstagramConfidence.ELEVE

    if full_name and strong_name_handle_match(restaurant_name, full_name):
        return InstagramConfidence.ELEVE

    if biography and strong_name_handle_match(restaurant_name, biography):
        # Contenance du nom compact dans la bio compactée.
        return InstagramConfidence.ELEVE

    partial = _partial_token_match(restaurant_name, handle)
    if full_name and _partial_token_match(restaurant_name, full_name):
        partial = True

    if not partial:
        return InstagramConfidence.FAIBLE

    if _handle_suggests_different_place(restaurant_name, handle):
        return InstagramConfidence.FAIBLE

    city_confirmed = False
    if compact_text(city) and (
        (biography and city_appears_in_bio(city, biography))
        or compact_text(city) in compact_text(handle)
    ):
        city_confirmed = True

    if city_confirmed:
        return InstagramConfidence.ELEVE

    return InstagramConfidence.MOYEN
