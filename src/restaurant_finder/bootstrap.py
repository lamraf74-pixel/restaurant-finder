"""Composition root : câble les implémentations concrètes entre elles.

Isoler ce câblage dans un seul module permet de garder `cli.py` focalisé
sur la présentation, et de changer une implémentation (ex: un autre
`SearchProvider`) sans toucher à la logique métier ni à la CLI.
"""

from __future__ import annotations

from restaurant_finder.cache import FileCache
from restaurant_finder.config import Settings
from restaurant_finder.enrichment.instagram_finder import InstagramFinder
from restaurant_finder.enrichment.search_providers.ddgs_provider import DdgsSearchProvider
from restaurant_finder.geocoding.nominatim_client import NominatimGeocoder
from restaurant_finder.http.client import build_http_session
from restaurant_finder.services.restaurant_finder_service import RestaurantFinderService
from restaurant_finder.sources.overpass_source import OverpassRestaurantSource


def build_service(settings: Settings, enable_instagram: bool = True) -> RestaurantFinderService:
    """Construit un `RestaurantFinderService` entièrement câblé et prêt à l'emploi."""

    session = build_http_session(settings)
    # Overpass : zéro retry HTTP — un échec doit basculer immédiatement sur le miroir suivant.
    overpass_session = build_http_session(settings, max_retries=0)
    cache = FileCache(
        cache_dir=settings.cache_dir,
        ttl_seconds=settings.cache_ttl_seconds,
        enabled=settings.cache_enabled,
    )

    geocoder = NominatimGeocoder(session=session, settings=settings, cache=cache)
    source = OverpassRestaurantSource(
        session=overpass_session, settings=settings, geocoder=geocoder
    )

    instagram_finder: InstagramFinder | None = None
    if enable_instagram and settings.instagram_search_enabled:
        # ddgs (sans clé API) : plus fiable que le scraping HTML DuckDuckGo.
        search_provider = DdgsSearchProvider(settings=settings)
        instagram_finder = InstagramFinder(
            search_provider=search_provider, settings=settings, cache=cache
        )

    return RestaurantFinderService(
        source=source, settings=settings, instagram_finder=instagram_finder
    )
