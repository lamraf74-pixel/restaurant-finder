"""Interface abstraite d'un fournisseur de recherche web.

Il n'existe pas d'API gratuite officielle de recherche web permettant de
retrouver un profil Instagram. Cette interface isole ce point de risque :
`DuckDuckGoSearchProvider` (scraping HTML, gratuit mais fragile) peut être
remplacé par un fournisseur payant plus fiable (SerpApi, Google Custom
Search...) en implémentant simplement ce même contrat.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel


class SearchResult(BaseModel):
    """Un résultat de recherche web générique."""

    title: str
    url: str
    snippet: str = ""


class SearchProvider(ABC):
    """Contrat pour tout fournisseur de recherche web."""

    @abstractmethod
    def search(self, query: str, max_results: int) -> list[SearchResult]:
        """Exécute une recherche web et retourne jusqu'à `max_results` résultats."""
        raise NotImplementedError
