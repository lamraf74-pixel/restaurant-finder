"""Client de lecture d'un profil Instagram public (nom, bio, followers).

Instagram ne propose pas d'API publique gratuite pour cela. On lit la page
profil web (comme un navigateur) et on extrait les champs du JSON embarqué
dans le HTML. Fragile si Meta change le HTML, mais isolé derrière une seule
classe remplaçable.

Ce client sert deux besoins avec une seule requête réseau par compte :
1. Vérifier qu'un candidat trouvé par recherche web correspond bien au
   restaurant (nom complet + biographie sont bien plus fiables qu'un
   simple extrait de résultat de recherche) — voir `InstagramFinder`.
2. Récupérer le nombre de followers pour le filtre `--max-followers`.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from typing import NamedTuple

import requests

from restaurant_finder.cache import FileCache
from restaurant_finder.config import Settings
from restaurant_finder.enrichment.instagram_normalize import extract_handle

logger = logging.getLogger(__name__)

#: Capture le contenu JSON entre guillemets, y compris les séquences échappées (\n, \", \uXXXX...).
_JSON_STRING_BODY = r'((?:[^"\\]|\\.)*)"'
_FOLLOWER_COUNT_PATTERN = re.compile(r'"follower_count"\s*:\s*(\d+)')
_FULL_NAME_PATTERN = re.compile(r'"full_name"\s*:\s*"' + _JSON_STRING_BODY)
_BIOGRAPHY_PATTERN = re.compile(r'"biography"\s*:\s*"' + _JSON_STRING_BODY)
_IS_PRIVATE_PATTERN = re.compile(r'"is_private"\s*:\s*(true|false)')

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
        "Mobile/15E148 Safari/604.1"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
}


class InstagramProfile(NamedTuple):
    """Informations publiques extraites de la page d'un compte Instagram."""

    username: str
    full_name: str
    biography: str
    follower_count: int | None
    is_private: bool

    def to_cache_dict(self) -> dict[str, object]:
        return {
            "username": self.username,
            "full_name": self.full_name,
            "biography": self.biography,
            "follower_count": self.follower_count,
            "is_private": self.is_private,
        }

    @classmethod
    def from_cache_dict(cls, data: dict[str, object]) -> InstagramProfile:
        raw_followers = data.get("follower_count")
        return cls(
            username=str(data.get("username", "")),
            full_name=str(data.get("full_name", "")),
            biography=str(data.get("biography", "")),
            follower_count=int(str(raw_followers)) if raw_followers is not None else None,
            is_private=bool(data.get("is_private", False)),
        )


class InstagramProfileClient:
    """Récupère et met en cache le profil public d'un compte Instagram."""

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

    def get_profile(self, instagram_url_or_handle: str) -> InstagramProfile | None:
        """Retourne le profil public, ou None si illisible / privé / bloqué."""

        handle = extract_handle(instagram_url_or_handle)
        if handle is None:
            return None

        cache_key = f"instagram_profile:{handle.lower()}"
        if self._cache is not None:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return InstagramProfile.from_cache_dict(cached) if cached else None

        profile = self._fetch_profile(handle)

        if self._cache is not None:
            # On cache aussi les échecs ({}), pour ne pas retaper Instagram en boucle.
            self._cache.set(cache_key, profile.to_cache_dict() if profile else {})

        return profile

    def get_follower_count(self, instagram_url_or_handle: str) -> int | None:
        """Retourne le nombre de followers (raccourci pratique sur `get_profile`)."""

        profile = self.get_profile(instagram_url_or_handle)
        return profile.follower_count if profile else None

    def _fetch_profile(self, handle: str) -> InstagramProfile | None:
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

            return self._parse_profile(handle, response.text)

    @staticmethod
    def _parse_profile(handle: str, html: str) -> InstagramProfile | None:
        follower_match = _FOLLOWER_COUNT_PATTERN.search(html)
        if not follower_match:
            logger.warning(
                "Profil @%s illisible (page bloquée, profil privé ou compte inexistant).",
                handle,
            )
            return None

        is_private_match = _IS_PRIVATE_PATTERN.search(html)

        return InstagramProfile(
            username=handle,
            full_name=_decode_json_string(_FULL_NAME_PATTERN.search(html)),
            biography=_decode_json_string(_BIOGRAPHY_PATTERN.search(html)),
            follower_count=int(follower_match.group(1)),
            is_private=is_private_match is not None and is_private_match.group(1) == "true",
        )

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


def _decode_json_string(match: re.Match[str] | None) -> str:
    """Décode une sous-chaîne JSON capturée (gère \\n, \\", \\uXXXX...)."""

    if match is None:
        return ""
    try:
        return json.loads(f'"{match.group(1)}"')
    except (json.JSONDecodeError, ValueError):
        return match.group(1)
