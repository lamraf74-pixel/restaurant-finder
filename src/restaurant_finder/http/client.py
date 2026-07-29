"""Fabrique de session HTTP partagée, avec retries et User-Agent identifié.

Nominatim et Overpass exigent tous deux un User-Agent explicite (leurs
politiques d'usage interdisent le User-Agent par défaut des librairies
HTTP). Centraliser la création de la session garantit que toutes les
requêtes sortantes respectent cette règle.
"""

from __future__ import annotations

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from restaurant_finder.config import Settings


def build_http_session(settings: Settings) -> requests.Session:
    """Construit une `requests.Session` configurée pour l'application."""

    session = requests.Session()
    session.headers.update({"User-Agent": settings.user_agent})

    retry_strategy = Retry(
        total=settings.http_max_retries,
        backoff_factor=settings.http_backoff_factor,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET", "POST"),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    return session
