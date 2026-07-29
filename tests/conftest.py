"""Fixtures partagées pour la suite de tests."""

from __future__ import annotations

import pytest

from restaurant_finder.domain.models import Restaurant


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
