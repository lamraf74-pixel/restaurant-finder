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
        from restaurant_finder.domain.models import InstagramConfidence

        if on_progress is not None:
            on_progress(len(restaurants), len(restaurants))
        for restaurant in restaurants:
            if not restaurant.instagram_url:
                restaurant.instagram_url = "https://www.instagram.com/stub_compte/"
            if restaurant.instagram_confidence is None:
                restaurant.instagram_confidence = InstagramConfidence.ELEVE
        return restaurants

    @staticmethod
    def prepare_export_list(restaurants):  # type: ignore[no-untyped-def]
        from restaurant_finder.services.restaurant_finder_service import (
            RestaurantFinderService,
        )

        return RestaurantFinderService.prepare_export_list(restaurants)

    @staticmethod
    def keep_active_accounts(restaurants):  # type: ignore[no-untyped-def]
        from restaurant_finder.services.restaurant_finder_service import (
            RestaurantFinderService,
        )

        return RestaurantFinderService.keep_active_accounts(restaurants)

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


def test_search_passes_max_post_age_days_to_service_settings(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def factory(settings, enable_instagram):  # type: ignore[no-untyped-def]
        captured["max_post_age_days"] = settings.instagram_max_post_age_days
        captured["max_followers"] = settings.instagram_max_followers
        return _StubService(_sample_restaurants())

    app = create_app(Settings(), service_factory=factory, output_root=tmp_path)
    client = TestClient(app)

    response = client.post(
        "/api/search",
        json={
            "cities": ["Rennes"],
            "formats": ["xlsx"],
            "enrich_instagram": True,
            "max_followers": 6000,
            "max_post_age_days": 30,
        },
    )
    assert response.status_code == 200
    job = _wait_for_job(client, response.json()["job_id"])

    assert job["status"] == "done"
    assert captured["max_post_age_days"] == 30
    assert captured["max_followers"] == 6000
    assert "Actifs" in job["message"]
    assert "activité ≤ 30j" in job["message"]


def test_index_includes_default_activity_filter_and_cache_bust() -> None:
    from pathlib import Path

    html = Path("src/restaurant_finder/webapp/static/index.html").read_text(encoding="utf-8")
    assert 'id="max-post-age-days-input"' in html
    assert 'value="30"' in html
    assert "app.js?v=5" in html
