"""Interprétation d'une localisation fournie par l'utilisateur.

Objectif produit : permettre de « pinguer » un lieu sur Google Maps et de
coller directement ce que Google Maps propose de copier, à savoir :

- des coordonnées brutes, ex: "45.917707, 6.131942" (clic droit -> le
  premier élément du menu copie exactement ce format) ;
- une URL Google Maps contenant les coordonnées dans son chemin
  (`/@lat,lon,zoom`) ou ses paramètres (`?q=lat,lon`, `&ll=lat,lon`) ;
- un lien court (`https://maps.app.goo.gl/...`), résolu via une requête
  HTTP pour retrouver l'URL complète.
"""

from __future__ import annotations

import logging
import re

import requests

from restaurant_finder.config import Settings
from restaurant_finder.exceptions import LocationParsingError

logger = logging.getLogger(__name__)

_PLAIN_COORDINATES = re.compile(
    r"^\s*(-?\d{1,3}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)\s*$"
)
_URL_AT_PATTERN = re.compile(r"@(-?\d{1,3}\.\d+),(-?\d{1,3}\.\d+)")
_URL_QUERY_PATTERNS = (
    re.compile(r"[?&]q=(-?\d{1,3}\.\d+),(-?\d{1,3}\.\d+)"),
    re.compile(r"[?&]query=(-?\d{1,3}\.\d+),(-?\d{1,3}\.\d+)"),
    re.compile(r"[?&]ll=(-?\d{1,3}\.\d+),(-?\d{1,3}\.\d+)"),
)
class LocationInputParser:
    """Convertit un texte (coordonnées ou lien Google Maps) en (latitude, longitude)."""

    def __init__(self, session: requests.Session, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    def parse(self, raw_input: str) -> tuple[float, float]:
        """Retourne (latitude, longitude), ou lève `LocationParsingError`."""

        text = raw_input.strip()
        if not text:
            raise LocationParsingError("Valeur vide.")

        coordinates = self._try_plain_coordinates(text)
        if coordinates is not None:
            return coordinates

        coordinates = self._try_url_patterns(text)
        if coordinates is not None:
            return coordinates

        if self._looks_like_url(text):
            resolved_url = self._resolve_redirect(text)
            if resolved_url and resolved_url != text:
                coordinates = self._try_url_patterns(resolved_url)
                if coordinates is not None:
                    return coordinates

        raise LocationParsingError(
            f"Impossible d'interpréter {raw_input!r} comme des coordonnées GPS ou un lien "
            "Google Maps. Copie soit les coordonnées ('45.9177, 6.1319'), soit l'URL complète."
        )

    @staticmethod
    def _try_plain_coordinates(text: str) -> tuple[float, float] | None:
        match = _PLAIN_COORDINATES.match(text)
        if not match:
            return None
        return _to_coordinates(match.group(1), match.group(2))

    @staticmethod
    def _try_url_patterns(text: str) -> tuple[float, float] | None:
        at_match = _URL_AT_PATTERN.search(text)
        if at_match:
            return _to_coordinates(at_match.group(1), at_match.group(2))

        for pattern in _URL_QUERY_PATTERNS:
            match = pattern.search(text)
            if match:
                return _to_coordinates(match.group(1), match.group(2))

        return None

    @staticmethod
    def _looks_like_url(text: str) -> bool:
        return text.lower().startswith(("http://", "https://"))

    def _resolve_redirect(self, url: str) -> str | None:
        """Suit les redirections d'un lien court Google Maps pour révéler les coordonnées."""

        try:
            response = self._session.get(
                url,
                timeout=self._settings.request_timeout_seconds,
                allow_redirects=True,
            )
        except requests.RequestException as exc:
            logger.debug("Résolution du lien %r échouée : %s", url, exc)
            return None

        return response.url


def _to_coordinates(raw_latitude: str, raw_longitude: str) -> tuple[float, float]:
    latitude, longitude = float(raw_latitude), float(raw_longitude)
    if not (-90 <= latitude <= 90) or not (-180 <= longitude <= 180):
        raise LocationParsingError(
            f"Coordonnées hors limites : ({latitude}, {longitude})."
        )
    return latitude, longitude
