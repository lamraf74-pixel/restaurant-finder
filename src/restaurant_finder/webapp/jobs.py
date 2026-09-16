"""Gestion des recherches lancées depuis le panel web, en arrière-plan.

Le panel web est un outil local mono-utilisateur : un simple dictionnaire
protégé par verrou, avec un thread par recherche, suffit largement (pas
besoin de file d'attente distribuée type Celery/Redis).
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from restaurant_finder.bootstrap import build_service
from restaurant_finder.config import Settings
from restaurant_finder.domain.models import Restaurant
from restaurant_finder.exceptions import RestaurantFinderError
from restaurant_finder.export import EXPORTERS
from restaurant_finder.filtering.cuisine_filter import parse_cuisine_values
from restaurant_finder.geocoding.geo_math import PointQuery
from restaurant_finder.services.restaurant_finder_service import RestaurantFinderService
from restaurant_finder.webapp.schemas import JobStatusResponse, ResultRow, SearchRequest

logger = logging.getLogger(__name__)

#: Fabrique de service injectable (facilite les tests avec un service stub).
ServiceFactory = Callable[[Settings, bool], RestaurantFinderService]


def _count_by_confidence(restaurants: list[Restaurant]) -> dict[str, int]:
    """Compte les associations Instagram par niveau de confiance (ordre d'affichage)."""

    counts: dict[str, int] = {}
    for restaurant in restaurants:
        if restaurant.instagram_confidence is None:
            continue
        label = restaurant.instagram_confidence.value
        counts[label] = counts.get(label, 0) + 1
    return counts


@dataclass
class _Job:
    job_id: str
    status: str = "pending"
    message: str = ""
    progress_done: int = 0
    progress_total: int = 0
    restaurants: list[Restaurant] = field(default_factory=list)
    file_paths: dict[str, Path] = field(default_factory=dict)
    error: str | None = None

    def to_response(self) -> JobStatusResponse:
        results = (
            [
                ResultRow(
                    name=restaurant.name,
                    instagram=restaurant.instagram_handle,
                    instagram_followers=restaurant.instagram_followers,
                    instagram_confidence=(
                        restaurant.instagram_confidence.value
                        if restaurant.instagram_confidence
                        else None
                    ),
                    activity_status=restaurant.activity_status or None,
                    address=restaurant.address,
                    city=restaurant.city,
                    category=restaurant.category,
                )
                for restaurant in self.restaurants
            ]
            if self.status == "done"
            else []
        )
        return JobStatusResponse(
            job_id=self.job_id,
            status=self.status,
            message=self.message,
            progress_done=self.progress_done,
            progress_total=self.progress_total,
            results=results,
            formats=list(self.file_paths.keys()),
            error=self.error,
        )


class JobManager:
    """Exécute les recherches du panel web en arrière-plan et suit leur avancement."""

    def __init__(
        self,
        settings: Settings,
        service_factory: ServiceFactory = build_service,
        output_root: Path | None = None,
    ) -> None:
        self._settings = settings
        self._service_factory = service_factory
        self._output_root = output_root or (settings.default_output_dir / "webapp")
        self._jobs: dict[str, _Job] = {}
        self._lock = threading.Lock()

    def start(self, payload: SearchRequest) -> str:
        """Valide la requête, crée un job et lance la recherche dans un thread."""

        if not payload.cities and not payload.points:
            raise ValueError("Précise au moins une ville ou un lieu sur la carte.")

        invalid_formats = set(payload.formats) - set(EXPORTERS)
        if invalid_formats:
            raise ValueError(f"Format(s) inconnu(s) : {', '.join(sorted(invalid_formats))}")
        if not payload.formats:
            raise ValueError("Choisis au moins un format d'export (CSV et/ou Excel).")

        job_id = uuid.uuid4().hex[:12]
        job = _Job(job_id=job_id, status="pending", message="En attente...")
        with self._lock:
            self._jobs[job_id] = job

        thread = threading.Thread(target=self._run, args=(job, payload), daemon=True)
        thread.start()
        return job_id

    def get(self, job_id: str) -> _Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def _run(self, job: _Job, payload: SearchRequest) -> None:
        try:
            settings = self._settings.model_copy(
                update={
                    "instagram_max_followers": payload.max_followers,
                    "instagram_exclude_unknown_followers": not payload.keep_unknown_followers,
                    "instagram_max_post_age_days": payload.max_post_age_days,
                }
            )
            logger.info(
                "Job %s : max_followers=%s keep_unknown_followers=%s max_post_age_days=%s",
                job.job_id,
                payload.max_followers,
                payload.keep_unknown_followers,
                payload.max_post_age_days,
            )
            service = self._service_factory(settings, payload.enrich_instagram)

            job.status = "fetching"
            job.message = "Récupération des établissements (OpenStreetMap)..."

            near_points = [
                PointQuery(point.latitude, point.longitude, point.radius_meters)
                for point in payload.points
            ]

            restaurants = service.find_restaurants(
                cities=payload.cities or None,
                near_points=near_points or None,
                categories=payload.categories or None,
                limit=payload.limit,
                enrich_instagram=False,
                exclude_chains=not payload.include_chains,
                cuisines=parse_cuisine_values(payload.cuisine),
            )

            if not restaurants:
                job.status = "done"
                job.message = "Aucun établissement trouvé pour cette recherche."
                return

            dropped_inactive = 0
            if payload.enrich_instagram:
                job.status = "enriching"
                job.progress_total = len(restaurants)
                job.message = f"Recherche des profils Instagram (0/{len(restaurants)})..."

                def on_progress(done: int, total: int) -> None:
                    job.progress_done = done
                    job.progress_total = total
                    job.message = f"Recherche des profils Instagram ({done}/{total})..."

                restaurants = service.enrich_with_instagram(restaurants, on_progress=on_progress)
                restaurants = service.prepare_export_list(restaurants)
                before_active = len(restaurants)
                restaurants = service.keep_active_accounts(restaurants)
                dropped_inactive = before_active - len(restaurants)

                if payload.only_with_instagram:
                    restaurants = [r for r in restaurants if r.instagram_url]

            if not restaurants:
                job.status = "done"
                job.message = (
                    "Aucun établissement avec Instagram actif trouvé."
                    if payload.enrich_instagram
                    else "Aucun établissement trouvé."
                )
                return

            job.status = "exporting"
            job.message = "Export des fichiers..."

            destination = self._output_root / job.job_id / "resultats"
            exporters = [EXPORTERS[fmt] for fmt in payload.formats]
            exported_paths = service.export(restaurants, exporters, destination)
            job.file_paths = dict(zip(payload.formats, exported_paths, strict=True))

            job.restaurants = restaurants
            job.status = "done"
            job.message = f"{len(restaurants)} établissement(s) Actifs exporté(s)."
            if payload.enrich_instagram:
                parts: list[str] = []
                if payload.max_post_age_days:
                    parts.append(f"activité ≤ {payload.max_post_age_days}j")
                if dropped_inactive:
                    parts.append(f"{dropped_inactive} Inactifs écartés")
                by_confidence = _count_by_confidence(restaurants)
                if by_confidence:
                    parts.append(
                        ", ".join(f"{label}: {count}" for label, count in by_confidence.items())
                    )
                if parts:
                    job.message += f" ({' ; '.join(parts)})."
        except RestaurantFinderError as exc:
            job.status = "error"
            job.error = str(exc)
            logger.warning("Échec du job %s : %s", job.job_id, exc)
        except Exception as exc:  # noqa: BLE001 - isole toute erreur inattendue du thread
            job.status = "error"
            job.error = f"Erreur inattendue : {exc}"
            logger.exception("Erreur inattendue dans le job %s", job.job_id)
