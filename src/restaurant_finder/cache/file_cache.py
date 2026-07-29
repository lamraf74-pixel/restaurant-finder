"""Cache disque simple, à base de fichiers JSON avec expiration (TTL).

Objectif : éviter de re-solliciter Nominatim / Overpass / DuckDuckGo à
chaque exécution pour les mêmes requêtes, ce qui est à la fois plus
rapide et plus respectueux des services publics gratuits utilisés.

Volontairement minimaliste (pas de dépendance externe type `diskcache`)
car le cahier des charges privilégie une infrastructure légère.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class FileCache:
    """Cache clé/valeur persistant sur disque, avec durée de vie (TTL)."""

    def __init__(self, cache_dir: Path, ttl_seconds: int, enabled: bool = True) -> None:
        self._cache_dir = cache_dir
        self._ttl_seconds = ttl_seconds
        self._enabled = enabled
        if self._enabled:
            self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self._cache_dir / f"{digest}.json"

    def get(self, key: str) -> Any | None:
        """Retourne la valeur en cache pour `key`, ou None si absente/expirée."""

        if not self._enabled:
            return None

        path = self._path_for(key)
        if not path.exists():
            return None

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.debug("Cache illisible pour %s (%s), on l'ignore.", key, exc)
            return None

        if time.time() > payload.get("expires_at", 0):
            path.unlink(missing_ok=True)
            return None

        return payload.get("value")

    def set(self, key: str, value: Any) -> None:
        """Enregistre `value` en cache pour `key`, avec le TTL configuré."""

        if not self._enabled:
            return

        path = self._path_for(key)
        payload = {"expires_at": time.time() + self._ttl_seconds, "value": value}
        try:
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except OSError as exc:
            logger.debug("Impossible d'écrire le cache pour %s (%s).", key, exc)
