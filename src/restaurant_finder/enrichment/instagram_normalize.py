"""Normalisation des identifiants / URLs Instagram.

Les tags OSM et les résultats de recherche renvoient des formats
hétérogènes (@handle, URL complète, chemin /popular/, etc.).
Ce module centralise la conversion vers une URL de profil canonique.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

_INSTAGRAM_HOST_PATTERN = re.compile(r"(^|\.)instagram\.com$", re.IGNORECASE)
_RESERVED_PATH_SEGMENTS = {
    "p",
    "reel",
    "reels",
    "explore",
    "accounts",
    "stories",
    "directory",
    "developer",
    "about",
    "legal",
    "tv",
    "popular",
    "tags",
    "locations",
}
_HANDLE_PATTERN = re.compile(r"^[A-Za-z0-9._]{1,30}$")
_HANDLE_FROM_PATH = re.compile(r"^/([A-Za-z0-9._]+)/?")
_HANDLE_FROM_TEXT = re.compile(
    r"(?:https?://)?(?:www\.)?instagram\.com/([A-Za-z0-9._]+)/?",
    re.IGNORECASE,
)


def extract_handle(value: str | None) -> str | None:
    """Extrait un handle Instagram depuis une URL, un @handle ou un texte libre."""

    if not value:
        return None

    text = value.strip()
    if not text:
        return None

    if text.startswith("@"):
        text = text[1:].strip()

    match = _HANDLE_FROM_TEXT.search(text)
    if match:
        handle = match.group(1)
        if handle.lower() not in _RESERVED_PATH_SEGMENTS and _HANDLE_PATTERN.match(handle):
            return handle

    parsed = urlparse(text if "://" in text else f"https://{text}")
    if _INSTAGRAM_HOST_PATTERN.search(parsed.netloc):
        path_match = _HANDLE_FROM_PATH.match(parsed.path)
        if path_match:
            handle = path_match.group(1)
            if handle.lower() not in _RESERVED_PATH_SEGMENTS and _HANDLE_PATTERN.match(handle):
                return handle
        return None

    # Valeur OSM du type "mon_resto_nice" sans URL.
    candidate = text.strip("/")
    if _HANDLE_PATTERN.match(candidate) and candidate.lower() not in _RESERVED_PATH_SEGMENTS:
        return candidate

    return None


def extract_handles_from_text(value: str | None) -> list[str]:
    """Extrait tous les handles Instagram mentionnés dans un texte libre.

    Utile pour les extraits de résultats de recherche où l'URL principale
    n'est pas Instagram, mais le titre ou le snippet cite
    ``instagram.com/nomcompte``.
    """

    if not value:
        return []

    handles: list[str] = []
    seen: set[str] = set()
    for match in _HANDLE_FROM_TEXT.finditer(value):
        handle = match.group(1)
        if handle.lower() in _RESERVED_PATH_SEGMENTS:
            continue
        if not _HANDLE_PATTERN.match(handle):
            continue
        key = handle.lower()
        if key in seen:
            continue
        seen.add(key)
        handles.append(handle)
    return handles


def to_profile_url(value: str | None) -> str | None:
    """Convertit une valeur Instagram quelconque en URL de profil canonique."""

    handle = extract_handle(value)
    if handle is None:
        return None
    return f"https://www.instagram.com/{handle}/"
