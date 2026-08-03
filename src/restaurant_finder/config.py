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
    # Les instances publiques sont souvent saturées (406 / timeouts). On essaie
    # plusieurs miroirs ; un miroir qui répond 200 avec une base de données
    # invalide / vide est écarté (ex. certains miroirs « fantômes »).
    # Les retries HTTP sur Overpass sont désactivés : un échec = miroir suivant.
    overpass_base_url: str = "https://overpass-api.de/api/interpreter"
    overpass_fallback_urls: tuple[str, ...] = (
        "https://z.overpass-api.de/api/interpreter",
        "https://lz4.overpass-api.de/api/interpreter",
    )
    overpass_timeout_seconds: int = 60
    overpass_connect_timeout_seconds: float = 10.0
    overpass_busy_retry_seconds: float = 8.0
    # Pause entre deux requêtes Overpass successives (recherche multi-points).
    overpass_rate_limit_seconds: float = 3.0
    # Par défaut : restaurants & cafés (les indépendants / bistrots ciblés).
    # Les bars / pubs / fast-food restent disponibles via --category.
    default_categories: tuple[str, ...] = ("restaurant", "cafe")
    # Rayon par défaut (mètres) autour de chaque point "pingué" (--near).
    default_search_radius_meters: float = 800.0

    # --- Enrichissement Instagram ---
    # workers=1 : les backends de recherche publics supportent mal le parallèle.
    instagram_search_enabled: bool = True
    instagram_search_max_workers: int = 1
    instagram_search_delay_seconds: float = 1.0
    instagram_match_threshold: int = 55  # score rapidfuzz (0-100)
    instagram_max_search_results: int = 10
    # Ne garder que les comptes avec strictement moins de N followers.
    instagram_max_followers: int = 1000
    instagram_filter_by_followers: bool = True
    # Si le nombre de followers est illisible (blocage IG), exclure le compte.
    instagram_exclude_unknown_followers: bool = True
    instagram_followers_delay_seconds: float = 1.5

    # --- Cache ---
    cache_enabled: bool = True
    cache_dir: Path = Path(".cache/restaurant_finder")
    cache_ttl_seconds: int = 7 * 24 * 60 * 60  # 7 jours

    # --- Export ---
    default_output_dir: Path = Path("output")


def get_settings() -> Settings:
    """Point d'accès unique à la configuration (facilite les tests via monkeypatch)."""

    return Settings()
