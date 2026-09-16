"""Client de lecture d'un profil Instagram public (nom, bio, followers, activité).

Instagram ne propose pas d'API publique gratuite pour cela. On lit la page
profil web (comme un navigateur) et on extrait les champs du JSON embarqué
dans le HTML. Fragile si Meta change le HTML, mais isolé derrière une seule
classe remplaçable.

Ce client sert trois besoins avec une seule requête réseau par compte :
1. Vérifier qu'un candidat trouvé par recherche web correspond bien au
   restaurant (nom complet + biographie sont bien plus fiables qu'un
   simple extrait de résultat de recherche) — voir `InstagramFinder`.
2. Récupérer le nombre de followers pour le filtre `--max-followers`.
3. Récupérer la date du dernier post (`taken_at_timestamp`, id média
   ``POLARIS_*`` décodé, ou `latest_reel_media` en repli) pour le filtre
   `--max-post-age-days`. Cette date n'est pas toujours présente (mur de
   login, profil privé) : le filtre d'activité est donc opportuniste.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from datetime import datetime, timezone
from typing import NamedTuple

import requests

from restaurant_finder.cache import FileCache
from restaurant_finder.config import Settings
from restaurant_finder.enrichment.instagram_normalize import extract_handle
from restaurant_finder.utils.retry import call_with_retry

logger = logging.getLogger(__name__)

_TRANSIENT_NETWORK_ERRORS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)

#: Capture le contenu JSON entre guillemets, y compris les séquences échappées (\n, \", \uXXXX...).
_JSON_STRING_BODY = r'((?:[^"\\]|\\.)*)"'
_FOLLOWER_COUNT_PATTERN = re.compile(r'"follower_count"\s*:\s*(\d+)')
_FULL_NAME_PATTERN = re.compile(r'"full_name"\s*:\s*"' + _JSON_STRING_BODY)
_BIOGRAPHY_PATTERN = re.compile(r'"biography"\s*:\s*"' + _JSON_STRING_BODY)
_IS_PRIVATE_PATTERN = re.compile(r'"is_private"\s*:\s*(true|false)')
_TAKEN_AT_PATTERN = re.compile(r'"taken_at_timestamp"\s*:\s*(\d+)')
_LATEST_REEL_PATTERN = re.compile(r'"latest_reel_media"\s*:\s*(\d+)')
_MEDIA_COUNT_PATTERN = re.compile(r'"media_count"\s*:\s*(\d+)')
#: Identifiants média du fil moderne (HTML Polaris) ; le premier = le plus récent.
_POLARIS_MEDIA_ID_PATTERN = re.compile(r'"id"\s*:\s*"POLARIS_(\d+)"')

#: Epoch Instagram (ms) pour décoder un media id « snowflake » en date.
_INSTAGRAM_EPOCH_MS = 1_314_220_021_721
#: Version de clé de cache profil : incrémenter si le parsing change.
_PROFILE_CACHE_VERSION = "v3"

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
    last_post_at: datetime | None = None
    media_count: int | None = None

    def to_cache_dict(self) -> dict[str, object]:
        return {
            "username": self.username,
            "full_name": self.full_name,
            "biography": self.biography,
            "follower_count": self.follower_count,
            "is_private": self.is_private,
            "last_post_at": self.last_post_at.isoformat() if self.last_post_at else None,
            "media_count": self.media_count,
        }

    @classmethod
    def from_cache_dict(cls, data: dict[str, object]) -> InstagramProfile:
        raw_followers = data.get("follower_count")
        raw_media = data.get("media_count")
        return cls(
            username=str(data.get("username", "")),
            full_name=str(data.get("full_name", "")),
            biography=str(data.get("biography", "")),
            follower_count=int(str(raw_followers)) if raw_followers is not None else None,
            is_private=bool(data.get("is_private", False)),
            last_post_at=_parse_cached_datetime(data.get("last_post_at")),
            media_count=int(str(raw_media)) if raw_media is not None else None,
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

        cache_key = f"instagram_profile:{_PROFILE_CACHE_VERSION}:{handle.lower()}"
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
                response = call_with_retry(
                    lambda: self._session.get(
                        f"https://www.instagram.com/{handle}/",
                        timeout=self._settings.request_timeout_seconds,
                    ),
                    operation=f"Lecture du profil Instagram @{handle}",
                    attempts=self._settings.retry_max_attempts,
                    base_delay=self._settings.retry_base_delay_seconds,
                    backoff_factor=self._settings.retry_backoff_factor,
                    retry_on=_TRANSIENT_NETWORK_ERRORS,
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
        media_count = _extract_media_count(html)

        return InstagramProfile(
            username=handle,
            full_name=_decode_json_string(_FULL_NAME_PATTERN.search(html)),
            biography=_decode_json_string(_BIOGRAPHY_PATTERN.search(html)),
            follower_count=int(follower_match.group(1)),
            is_private=is_private_match is not None and is_private_match.group(1) == "true",
            last_post_at=_extract_last_post_at(html),
            media_count=media_count,
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


def _unix_to_datetime(timestamp: int) -> datetime | None:
    """Convertit un timestamp Unix (secondes) en datetime UTC, ou None si invalide / nul."""

    if timestamp <= 0:
        return None
    try:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None


def _media_id_to_datetime(media_id: int) -> datetime | None:
    """Décode la date d'un media id Instagram (snowflake).

    Formule publique : ``(media_id >> 23) + epoch_instagram`` (ms depuis 1970).
    """

    if media_id <= 0:
        return None
    try:
        timestamp_ms = (media_id >> 23) + _INSTAGRAM_EPOCH_MS
        return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
    except (OSError, OverflowError, ValueError):
        return None


def _extract_media_count(html: str) -> int | None:
    """Nombre de posts si exposé, sinon nombre de médias Polaris visibles dans la page."""

    media_match = _MEDIA_COUNT_PATTERN.search(html)
    if media_match:
        return int(media_match.group(1))
    polaris_ids = _POLARIS_MEDIA_ID_PATTERN.findall(html)
    if polaris_ids:
        return len(polaris_ids)
    return None


def _extract_last_post_at(html: str) -> datetime | None:
    """Date du dernier média, si le JSON embarqué permet de la déduire.

    Priorité :
    1. ``taken_at_timestamp`` (ancien HTML)
    2. premier id ``POLARIS_<snowflake>`` du fil (HTML actuel)
    3. ``latest_reel_media`` si > 0

    Absent si Instagram n'a inclus ni fil ni date (mur de login, compte privé).
    """

    taken = _TAKEN_AT_PATTERN.search(html)
    if taken:
        parsed = _unix_to_datetime(int(taken.group(1)))
        if parsed is not None:
            return parsed

    polaris = _POLARIS_MEDIA_ID_PATTERN.search(html)
    if polaris:
        parsed = _media_id_to_datetime(int(polaris.group(1)))
        if parsed is not None:
            return parsed

    reel = _LATEST_REEL_PATTERN.search(html)
    if reel:
        return _unix_to_datetime(int(reel.group(1)))
    return None


def _parse_cached_datetime(value: object) -> datetime | None:
    """Relit une date ISO stockée en cache ; None si absente ou invalide."""

    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
