"""Sauvegarde de la progression d'une recherche, pour permettre une reprise.

Sur une grande recherche (`--limit 200`), l'enrichissement Instagram est la
phase longue (une requête réseau par établissement). Si le programme est
interrompu (Ctrl+C, plantage, coupure réseau) à mi-chemin, on veut pouvoir
relancer la même commande sans tout refaire.

Solution volontairement simple : un fichier JSON temporaire, sous
`<cache_dir>/progress/<run_id>.json`, mis à jour après chaque établissement
traité. Au démarrage, ce fichier est relu ; les établissements déjà présents
ne sont pas retraités (leur résultat Instagram est simplement réappliqué).

L'identifiant de recherche (`run_id`) est un hash du contenu exact de la
recherche (identifiants OSM des établissements à enrichir + réglages qui
influencent le résultat, ex: seuil de followers). Ainsi :

- Relancer exactement la même commande sur la même ville -> même `run_id`
  -> reprise automatique.
- Changer `--limit`, `--max-followers`, la ville, etc. -> `run_id` différent
  -> on repart d'une recherche "propre", sans réutiliser par erreur des
  résultats calculés avec d'autres critères.

Une fois la recherche entièrement terminée, le fichier est supprimé : il n'a
plus d'utilité et ne doit pas s'accumuler indéfiniment sur disque.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_PROGRESS_SUBDIR = "progress"


def progress_dir_for(cache_dir: Path) -> Path:
    """Répertoire où sont stockés les fichiers de progression, sous `cache_dir`."""

    return cache_dir / _PROGRESS_SUBDIR


def compute_run_id(osm_ids: Iterable[str], *extra: object) -> str:
    """Calcule un identifiant stable pour un lot de restaurants + critères.

    Deux appels avec le même ensemble de `osm_ids` (peu importe l'ordre) et
    les mêmes `extra` produisent le même identifiant.
    """

    payload = json.dumps(
        {"osm_ids": sorted(set(osm_ids)), "extra": [str(item) for item in extra]},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class SearchProgress:
    """Persiste, pour une recherche donnée (`run_id`), les restaurants déjà traités."""

    def __init__(self, progress_dir: Path, run_id: str) -> None:
        self._path = progress_dir / f"{run_id}.json"
        self._lock = threading.Lock()
        self._processed: dict[str, dict[str, Any]] = {}

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> dict[str, dict[str, Any]]:
        """Relit la progression sauvegardée (dict `osm_id` -> champs). Vide si absente."""

        if not self._path.exists():
            return {}

        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            processed = data.get("processed", {})
            if not isinstance(processed, dict):
                raise ValueError("format de progression invalide")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            logger.warning(
                "Fichier de progression illisible (%s) : %s — on repart de zéro.",
                self._path,
                exc,
            )
            return {}

        with self._lock:
            self._processed = dict(processed)
        return dict(self._processed)

    def mark_done(self, osm_id: str, fields: dict[str, Any]) -> None:
        """Enregistre `osm_id` comme traité et sauvegarde immédiatement sur disque."""

        with self._lock:
            self._processed[osm_id] = fields
            self._flush_locked()

    def clear(self) -> None:
        """Supprime la progression sauvegardée (recherche terminée, ou --fresh)."""

        with self._lock:
            self._processed = {}
            try:
                self._path.unlink(missing_ok=True)
            except OSError as exc:
                logger.debug("Impossible de supprimer %s : %s", self._path, exc)

    def _flush_locked(self) -> None:
        """Écrit l'état courant sur disque (appelant déjà sous `self._lock`)."""

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"updated_at": time.time(), "processed": self._processed}
            tmp_path = self._path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            tmp_path.replace(self._path)
        except OSError as exc:
            # Une progression qu'on ne peut pas sauvegarder ne doit pas interrompre
            # la recherche : on continue simplement sans filet de reprise.
            logger.warning("Impossible d'écrire la progression (%s) : %s", self._path, exc)
