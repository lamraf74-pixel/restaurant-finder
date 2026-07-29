from restaurant_finder.enrichment.search_providers.base import SearchProvider, SearchResult
from restaurant_finder.enrichment.search_providers.ddgs_provider import DdgsSearchProvider
from restaurant_finder.enrichment.search_providers.duckduckgo_provider import (
    DuckDuckGoSearchProvider,
)

__all__ = [
    "SearchProvider",
    "SearchResult",
    "DdgsSearchProvider",
    "DuckDuckGoSearchProvider",
]
