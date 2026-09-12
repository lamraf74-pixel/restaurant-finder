"""Fixtures partagées pour la suite de tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from restaurant_finder.domain.models import Restaurant


@pytest.fixture(autouse=True)
def _isolate_side_effect_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Empêche les tests d'écrire dans le `.cache/` ou le fichier de log réels.

    `RestaurantFinderService.enrich_with_instagram` (reprise), `FileCache` et
    `setup_logging` écrivent, par défaut, sous `Settings.cache_dir` /
    `Settings.log_file`. Rediriger ces valeurs par défaut vers un répertoire
    temporaire — via les mêmes variables d'environnement (`RF_...`) que
    l'utilisateur emploierait — isole chaque test sans devoir modifier chaque
    appel à `Settings(...)`.
    """

    monkeypatch.setenv("RF_CACHE_DIR", str(tmp_path / ".cache"))
    monkeypatch.setenv("RF_LOG_FILE", str(tmp_path / "restaurant-finder.log"))


@pytest.fixture
def sample_restaurant() -> Restaurant:
    return Restaurant(
        osm_id="node/1",
        name="Le Petit Bistrot",
        category="Restaurant",
        address="12 Rue de la République",
        city="Lyon",
        latitude=45.75,
        longitude=4.85,
    )
