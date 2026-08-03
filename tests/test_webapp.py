"""Tests d'intégration du panel web (FastAPI), avec un service stub."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from restaurant_finder.config import Settings
from restaurant_finder.domain.models import Restaurant
from restaurant_finder.webapp.server import create_app


class _StubService:
    """Remplace `RestaurantFinderService` pour tester l'API sans réseau."""

    def __init__(self, restaurants: list[Restaurant]) -> None:
        self._restaurants = restaurants

    def find_restaurants(self, **_: Any) -> list[Restaurant]:
        return list(self._restaurants)

    def enrich_with_instagram(self, restaurants, on_progress=None):  # type: ignore[no-untyped-def]
        if on_progress is not None:
            on_progress(len(restaurants), len(restaurants))
        return restaurants

    @staticmethod
    def export(restaurants, exporters, destination):  # type: ignore[no-untyped-def]
        return [exporter.export(restaurants, destination) for exporter in exporters]


def _stub_factory(restaurants: list[Restaurant]):
    def factory(settings, enable_instagram):  # type: ignore[no-untyped-def]
        return _StubService(restaurants)

    return factory


def _sample_restaurants() -> list[Restaurant]:
    return [
        Restaurant(
            osm_id="node/1", name="Le Petit Bistrot", category="Restaurant", city="Nice"
        )
    ]


def _wait_for_job(client: TestClient, job_id: str, timeout: float = 5.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        job = response.json()
        if job["status"] in ("done", "error"):
            return job
        time.sleep(0.05)
    raise TimeoutError("Le job n'a pas terminé à temps.")


def test_index_serves_html_page(tmp_path: Path) -> None:
    app = create_app(Settings(), service_factory=_stub_factory([]), output_root=tmp_path)
    client = TestClient(app)

    response = client.get("/")

    assert response.status_code == 200
    assert "Restaurant Finder" in response.text


def test_categories_endpoint_lists_known_categories(tmp_path: Path) -> None:
    app = create_app(Settings(), service_factory=_stub_factory([]), output_root=tmp_path)
    client = TestClient(app)

    response = client.get("/api/categories")

    assert response.status_code == 200
    assert "restaurant" in response.json()


def test_search_rejects_empty_request(tmp_path: Path) -> None:
    app = create_app(Settings(), service_factory=_stub_factory([]), output_root=tmp_path)
    client = TestClient(app)

    response = client.post("/api/search", json={})

    assert response.status_code == 400


def test_search_rejects_unknown_format(tmp_path: Path) -> None:
    app = create_app(Settings(), service_factory=_stub_factory([]), output_root=tmp_path)
    client = TestClient(app)

    response = client.post("/api/search", json={"cities": ["Nice"], "formats": ["pdf"]})

    assert response.status_code == 400


def test_full_search_flow_returns_results_and_allows_download(tmp_path: Path) -> None:
    restaurants = _sample_restaurants()
    app = create_app(
        Settings(), service_factory=_stub_factory(restaurants), output_root=tmp_path
    )
    client = TestClient(app)

    response = client.post(
        "/api/search",
        json={"cities": ["Nice"], "formats": ["csv"], "enrich_instagram": False},
    )
    assert response.status_code == 200
    job_id = response.json()["job_id"]

    job = _wait_for_job(client, job_id)

    assert job["status"] == "done"
    assert job["formats"] == ["csv"]
    assert [row["name"] for row in job["results"]] == ["Le Petit Bistrot"]

    download = client.get(f"/api/jobs/{job_id}/download/csv")
    assert download.status_code == 200
    assert "Le Petit Bistrot" in download.text


def test_unknown_job_returns_404(tmp_path: Path) -> None:
    app = create_app(Settings(), service_factory=_stub_factory([]), output_root=tmp_path)
    client = TestClient(app)

    response = client.get("/api/jobs/does-not-exist")

    assert response.status_code == 404
