"""Application FastAPI du panel web.

Aucune logique métier ici : chaque route délègue à `JobManager` (qui
lui-même délègue à `RestaurantFinderService`). Cette couche pourrait être
remplacée ou dupliquée (ex: une vraie SPA React) sans toucher au métier.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from restaurant_finder.bootstrap import build_service
from restaurant_finder.config import DEFAULT_CATEGORY_LABELS, Settings
from restaurant_finder.webapp.jobs import JobManager, ServiceFactory
from restaurant_finder.webapp.schemas import JobStatusResponse, SearchRequest

_STATIC_DIR = Path(__file__).parent / "static"


def create_app(
    settings: Settings,
    service_factory: ServiceFactory = build_service,
    output_root: Path | None = None,
) -> FastAPI:
    """Construit l'application FastAPI du panel (composition root de cette couche)."""

    app = FastAPI(title="Restaurant Finder", docs_url="/api/docs", redoc_url=None)
    job_manager = JobManager(
        settings=settings, service_factory=service_factory, output_root=output_root
    )

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse((_STATIC_DIR / "index.html").read_text(encoding="utf-8"))

    @app.get("/api/categories")
    def get_categories() -> dict[str, str]:
        return DEFAULT_CATEGORY_LABELS

    @app.get("/api/defaults")
    def get_defaults() -> dict[str, float | int]:
        return {
            "radius_meters": settings.default_search_radius_meters,
            "max_followers": settings.instagram_max_followers,
        }

    @app.post("/api/search")
    def start_search(payload: SearchRequest) -> dict[str, str]:
        try:
            job_id = job_manager.start(payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"job_id": job_id}

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> JobStatusResponse:
        job = job_manager.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Recherche introuvable.")
        return job.to_response()

    @app.get("/api/jobs/{job_id}/download/{export_format}")
    def download(job_id: str, export_format: str) -> FileResponse:
        job = job_manager.get(job_id)
        if job is None or export_format not in job.file_paths:
            raise HTTPException(status_code=404, detail="Fichier introuvable.")

        path = job.file_paths[export_format]
        if not path.exists():
            raise HTTPException(status_code=404, detail="Fichier introuvable.")

        return FileResponse(path, filename=path.name)

    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

    return app
