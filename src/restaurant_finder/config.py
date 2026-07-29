"""Configuration centralisée de l'application.

Toutes les valeurs sont surchargeables via des variables d'environnement
préfixées par `RF_` (ou un fichier `.env` à la racine du projet), ce qui
évite de disséminer des constantes magiques dans le code métier.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

#: Catégories OSM (tag `amenity`) supportées par défaut et leur libellé FR.
DEFAULT_CATEGORY_LABELS: dict[str, str] = {
    "restaurant": "Restaurant",
    "cafe": "Café",
    "fast_food": "Fast-food",
    "bar": "Bar",
    "pub": "Pub",
    "biergarten": "Biergarten",
}


class Settings(BaseSettings):
    """Paramètres de configuration, chargés depuis l'environnement / `.env`."""

    model_config = SettingsConfigDict(
        env_prefix="RF_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Réseau ---
    user_agent: str = "RestaurantFinder/0.1 (+https://github.com/example/restaurant-finder)"
    request_timeout_seconds: int = 30
    http_max_retries: int = 3
    http_backoff_factor: float = 1.0

    # --- Geocoding (Nominatim) ---
    nominatim_base_url: str = "https://nominatim.openstreetmap.org"
    nominatim_rate_limit_seconds: float = 1.0

    # --- Données restaurants (Overpass) ---
    # L'instance publique principale est parfois surchargée (timeouts, erreurs
    # transitoires) : on bascule automatiquement sur des miroirs de secours.
    overpass_base_url: str = "https://overpass-api.de/api/interpreter"
    overpass_fallback_urls: tuple[str, ...] = (
        "https://lz4.overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
    )
    overpass_rate_limit_seconds: float = 1.0
    default_categories: tuple[str, ...] = tuple(DEFAULT_CATEGORY_LABELS.keys())

    # --- Enrichissement Instagram ---
    instagram_search_enabled: bool = True
    instagram_search_max_workers: int = 3
    instagram_search_delay_seconds: float = 1.5
    instagram_match_threshold: int = 60  # score rapidfuzz (0-100)
    instagram_max_search_results: int = 8

    # --- Cache ---
    cache_enabled: bool = True
    cache_dir: Path = Path(".cache/restaurant_finder")
    cache_ttl_seconds: int = 7 * 24 * 60 * 60  # 7 jours

    # --- Export ---
    default_output_dir: Path = Path("output")


def get_settings() -> Settings:
    """Point d'accès unique à la configuration (facilite les tests via monkeypatch)."""

    return Settings()
