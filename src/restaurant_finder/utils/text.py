"""Fonctions utilitaires de normalisation de texte.

Utilisées à la fois pour la construction d'adresses et pour le matching
flou entre le nom d'un restaurant et les résultats de recherche web.
"""

from __future__ import annotations

import re
import unicodedata


def strip_accents(text: str) -> str:
    """Retire les accents d'une chaîne (é -> e, à -> a, ...)."""

    normalized = unicodedata.normalize("NFKD", text)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def normalize_text(text: str) -> str:
    """Normalise un texte pour le comparer de façon robuste.

    - minuscule
    - sans accents
    - sans ponctuation
    - espaces multiples réduits à un seul
    """

    text = strip_accents(text).lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def compact_text(text: str) -> str:
    """Comme `normalize_text`, mais sans aucun séparateur (espaces / tirets).

    Utile pour matcher un nom de restaurant avec un handle Instagram du type
    ``le_petit_bistrot`` ou ``lepetitbistrot``.
    """

    return normalize_text(text).replace(" ", "")


def join_non_empty(parts: list[str | None], separator: str = ", ") -> str:
    """Joint les éléments non vides d'une liste avec un séparateur."""

    return separator.join(part.strip() for part in parts if part and part.strip())
