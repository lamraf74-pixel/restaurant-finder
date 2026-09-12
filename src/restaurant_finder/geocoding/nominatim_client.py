"""Client de géocodage basé sur Nominatim (OpenStreetMap).

Rôle unique : transformer un nom de ville en zone géographique (bbox)
exploitable par la source Overpass. Isolé dans sa propre classe pour
pouvoir, demain, être remplacé par un autre fournisseur de géocodage
sans impacter le reste de l'application.
"""

from __future__ import annotations

import logging
import time

import requests

from restaurant_finder.cache import FileCache
from restaurant_finder.config import Settings
from restaurant_finder.domain.models import BoundingBox
from restaurant_finder.exceptions import GeocodingError
from restaurant_finder.utils.retry import call_with_retry

logger = logging.getLogger(__name__)

#: Erreurs réseau transitoires : on retente, plutôt qu'une réponse HTTP
#: d'erreur déjà obtenue (celle-ci est traitée telle quelle, sans retry).
_TRANSIENT_NETWORK_ERRORS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)


class NominatimGeocoder:
    """Géocode un nom de ville en `BoundingBox` via l'API Nominatim."""

    def __init__(
        self,
        session: requests.Session,
        settings: Settings,
        cache: FileCache | None = None,
    ) -> None:
        self._session = session
        self._settings = settings
        self._cache = cache
        self._last_request_time: float = 0.0

    def _respect_rate_limit(self) -> None:
        """Nominatim impose un maximum de 1 requête/seconde."""

        elapsed = time.monotonic() - self._last_request_time
        wait_time = self._settings.nominatim_rate_limit_seconds - elapsed
        if wait_time > 0:
            time.sleep(wait_time)

    def geocode_city(self, city: str) -> BoundingBox:
        """Retourne la zone géographique correspondant à `city`.

        Raises:
            GeocodingError: si la ville est introuvable ou en cas d'erreur réseau.
        """

        cache_key = f"geocode:{city.strip().lower()}"
        if self._cache is not None:
            cached = self._cache.get(cache_key)
            if cached is not None:
                logger.debug("Bounding box pour %r trouvée en cache.", city)
                return BoundingBox(**cached)

        self._respect_rate_limit()
        self._last_request_time = time.monotonic()

        try:
            response = call_with_retry(
                lambda: self._session.get(
                    f"{self._settings.nominatim_base_url}/search",
                    params={"city": city, "format": "jsonv2", "limit": "1"},
                    timeout=self._settings.request_timeout_seconds,
                ),
                operation=f"Géocodage Nominatim de {city!r}",
                attempts=self._settings.retry_max_attempts,
                base_delay=self._settings.retry_base_delay_seconds,
                backoff_factor=self._settings.retry_backoff_factor,
                retry_on=_TRANSIENT_NETWORK_ERRORS,
            )
            response.raise_for_status()
            results = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise GeocodingError(f"Échec du géocodage de la ville '{city}': {exc}") from exc

        if not results:
            raise GeocodingError(f"Ville introuvable : '{city}'.")

        raw_bbox = results[0].get("boundingbox")
        if not raw_bbox or len(raw_bbox) != 4:
            raise GeocodingError(f"Réponse Nominatim invalide pour '{city}'.")

        south, north, west, east = (float(value) for value in raw_bbox)
        bbox = BoundingBox(south=south, north=north, west=west, east=east)

        if self._cache is not None:
            self._cache.set(cache_key, bbox.model_dump())

        return bbox

    def reverse_geocode_city(self, latitude: float, longitude: float) -> str | None:
        """Retourne un nom de localité (ville/village) proche du point donné.

        Utilisé pour étiqueter la colonne "Ville" des recherches par point GPS
        (`--near`), où il n'y a pas de nom de ville fourni explicitement.
        Best-effort : retourne None si Nominatim échoue ou ne trouve rien.
        """

        cache_key = f"reverse:{round(latitude, 5)}:{round(longitude, 5)}"
        if self._cache is not None:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached or None

        self._respect_rate_limit()
        self._last_request_time = time.monotonic()

        try:
            response = call_with_retry(
                lambda: self._session.get(
                    f"{self._settings.nominatim_base_url}/reverse",
                    params={
                        "lat": f"{latitude:.6f}",
                        "lon": f"{longitude:.6f}",
                        "format": "jsonv2",
                        "zoom": "14",
                    },
                    timeout=self._settings.request_timeout_seconds,
                ),
                operation=f"Reverse géocodage Nominatim ({latitude}, {longitude})",
                attempts=self._settings.retry_max_attempts,
                base_delay=self._settings.retry_base_delay_seconds,
                backoff_factor=self._settings.retry_backoff_factor,
                retry_on=_TRANSIENT_NETWORK_ERRORS,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            logger.debug("Reverse géocodage échoué pour (%s, %s) : %s", latitude, longitude, exc)
            if self._cache is not None:
                self._cache.set(cache_key, "")
            return None

        address = payload.get("address", {})
        label = (
            address.get("city")
            or address.get("town")
            or address.get("village")
            or address.get("municipality")
            or address.get("suburb")
        )

        if self._cache is not None:
            self._cache.set(cache_key, label or "")

        return label
