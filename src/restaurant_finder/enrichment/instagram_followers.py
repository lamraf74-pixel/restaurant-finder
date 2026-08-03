"""Client de lecture du nombre de followers d'un profil Instagram public.

Instagram ne propose pas d'API publique gratuite pour cela. On lit la page
profil web (comme un navigateur) et on extrait `follower_count` du JSON
embarqué. Fragile si Meta change le HTML, mais isolé derrière une interface
remplaçable.
"""

from __future__ import annotations

import logging
import re
import threading
import time

import requests

from restaurant_finder.cache import FileCache
from restaurant_finder.config import Settings
from restaurant_finder.enrichment.instagram_normalize import extract_handle

logger = logging.getLogger(__name__)

_FOLLOWER_COUNT_PATTERN = re.compile(r'"follower_count"\s*:\s*(\d+)')
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
        "Mobile/15E148 Safari/604.1"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
}


class InstagramFollowerClient:
    """Récupère le nombre de followers d'un compte Instagram public."""

    def __init__(
        self,
        settings: Settings,
        cache: FileCache | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self._settings = settings
        self._cache = cache
        self._session = session or requests.Session()
        self._session.headers.update(_BROWSER_HEADERS)
        self._lock = threading.Lock()
        self._last_request_time = 0.0
        self._session_warmed = False

    def get_follower_count(self, instagram_url_or_handle: str) -> int | None:
        """Retourne le nombre de followers, ou None si illisible / privé / bloqué."""

        handle = extract_handle(instagram_url_or_handle)
        if handle is None:
            return None

        cache_key = f"instagram_followers:{handle.lower()}"
        if self._cache is not None:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return int(cached) if cached != "" else None

        count = self._fetch_follower_count(handle)

        if self._cache is not None:
            # On cache aussi les échecs (""), pour ne pas retaper Instagram en boucle.
            self._cache.set(cache_key, count if count is not None else "")

        return count

    def _fetch_follower_count(self, handle: str) -> int | None:
        with self._lock:
            self._respect_rate_limit()
            try:
                self._ensure_session()
                response = self._session.get(
                    f"https://www.instagram.com/{handle}/",
                    timeout=self._settings.request_timeout_seconds,
                )
                response.raise_for_status()
            except requests.RequestException as exc:
                logger.warning("Impossible de lire le profil @%s : %s", handle, exc)
                return None

            match = _FOLLOWER_COUNT_PATTERN.search(response.text)
            if not match:
                logger.warning(
                    "Nombre de followers introuvable pour @%s (page bloquée ou profil privé).",
                    handle,
                )
                return None

            count = int(match.group(1))
            logger.info("@%s : %d follower(s).", handle, count)
            return count

    def _ensure_session(self) -> None:
        if self._session_warmed:
            return
        try:
            self._session.get(
                "https://www.instagram.com/",
                timeout=self._settings.request_timeout_seconds,
            )
        except requests.RequestException as exc:
            logger.debug("Warm-up Instagram échoué : %s", exc)
        self._session_warmed = True

    def _respect_rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_request_time
        wait_time = self._settings.instagram_followers_delay_seconds - elapsed
        if wait_time > 0:
            time.sleep(wait_time)
        self._last_request_time = time.monotonic()
