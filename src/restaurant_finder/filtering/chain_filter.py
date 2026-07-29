"""Liste et détection des chaînes / franchises à exclure.

Objectif produit : ne garder que les restaurants et bistrots indépendants,
pas les grandes enseignes (McDo, Subway, Burger King, etc.).

Le filtre s'appuie sur :
1. le nom de l'établissement
2. les tags OSM `brand` / `operator` quand ils sont disponibles
"""

from __future__ import annotations

import re

from restaurant_finder.domain.models import Restaurant
from restaurant_finder.utils.text import normalize_text

#: Motifs normalisés (sans accents, minuscules) représentant des enseignes.
#: Suffisamment spécifiques pour limiter les faux positifs.
DEFAULT_CHAIN_PATTERNS: tuple[str, ...] = (
    # Fast-food internationaux
    r"\bmcdonald",
    r"\bmc ?do\b",
    r"\bburger ?king\b",
    r"\bkfc\b",
    r"\bsubway\b",
    r"\bquick\b",
    r"\bfive ?guys\b",
    r"\bwendy'?s\b",
    r"\btaco ?bell\b",
    r"\bnando'?s\b",
    r"\bchipotle\b",
    r"\bpopeyes\b",
    r"\bdunkin\b",
    r"\btim ?hortons\b",
    r"\bkrispy ?kreme\b",
    r"\bsteak ?n ?shake\b",
    # Pizza / burgers / tacos FR & international
    r"\bdomino'?s\b",
    r"\bpizza ?hut\b",
    r"\bpapa ?john",
    r"\bpizza ?pai\b",
    r"\bdel ?arte\b",
    r"\bspeed ?rabbit\b",
    r"\bla boite a pizza\b",
    r"\bo'?tacos\b",
    r"\bbig ?fernand\b",
    r"\bking ?marcel\b",
    r"\bbuffalo ?grill\b",
    r"\bhippopotamus\b",
    r"\bcourtepaille\b",
    r"\bflunch\b",
    r"\bindiana ?cafe\b",
    r"\bleon de bruxelles\b",
    r"\bhard ?rock\b",
    r"\bvapiano\b",
    r"\btgi ?friday",
    r"\bchicken ?street\b",
    r"\bfresh burritos\b",
    r"\bbearburger\b",
    # Café / boulangerie chaînes
    r"\bstarbucks\b",
    r"\bcosta ?coffee\b",
    r"\bcolumbus ?cafe\b",
    r"\bbagelstein\b",
    r"\bbrioche doree\b",
    r"\bla mie caline\b",
    r"\bboulangerie paul\b",
    r"\bpaul bakery\b",
    r"\bpomme de pain\b",
    r"\beric kayser\b",
    r"\bexki\b",
    r"\bcojean\b",
    r"\bpret a manger\b",
    r"\bclass'?croute\b",
    # Asiatique / sushis chaînes
    r"\bsushi ?shop\b",
    r"\bplanet ?sushi\b",
    r"\bsushi ?daily\b",
    r"\bpitaya\b",
    r"\bpokawa\b",
    r"\bmezzo di pasta\b",
    r"\bwok to walk\b",
    r"\byum yum\b",
    # Autres enseignes courantes
    r"\bbert'?s\b",
    r"\bautogrill\b",
    r"\brelay\b",
    r"\bcasino cafeteria\b",
)


class ChainRestaurantFilter:
    """Filtre les établissements appartenant à une chaîne / franchise connue."""

    def __init__(self, patterns: tuple[str, ...] | None = None) -> None:
        raw_patterns = patterns if patterns is not None else DEFAULT_CHAIN_PATTERNS
        self._compiled = [re.compile(pattern, re.IGNORECASE) for pattern in raw_patterns]

    def is_chain(self, restaurant: Restaurant) -> bool:
        """Retourne True si l'établissement ressemble à une enseigne connue."""

        haystacks = [
            normalize_text(restaurant.name),
            normalize_text(restaurant.brand or ""),
            normalize_text(restaurant.operator or ""),
        ]
        for haystack in haystacks:
            if not haystack:
                continue
            for pattern in self._compiled:
                if pattern.search(haystack):
                    return True
        return False

    def exclude_chains(self, restaurants: list[Restaurant]) -> tuple[list[Restaurant], int]:
        """Retourne (indépendants, nombre_exclus)."""

        independents: list[Restaurant] = []
        excluded = 0
        for restaurant in restaurants:
            if self.is_chain(restaurant):
                excluded += 1
            else:
                independents.append(restaurant)
        return independents, excluded
