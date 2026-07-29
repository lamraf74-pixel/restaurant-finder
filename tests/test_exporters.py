"""Tests des exporteurs CSV et Excel."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from restaurant_finder.domain.models import Restaurant
from restaurant_finder.export.csv_exporter import CsvExporter
from restaurant_finder.export.excel_exporter import ExcelExporter

_EXPECTED_COLUMNS = ["Nom", "Instagram", "Adresse", "Ville", "Catégorie"]


def _sample_restaurants(sample_restaurant: Restaurant) -> list[Restaurant]:
    other = Restaurant(
        osm_id="node/2",
        name="Café du Coin",
        category="Café",
        city="Lyon",
        instagram_url="https://www.instagram.com/cafeducoin/",
    )
    return [sample_restaurant, other]


def test_csv_exporter_writes_expected_columns_and_adds_extension(
    tmp_path: Path, sample_restaurant: Restaurant
) -> None:
    destination = tmp_path / "restaurants"

    exported_path = CsvExporter().export(_sample_restaurants(sample_restaurant), destination)

    assert exported_path == tmp_path / "restaurants.csv"
    dataframe = pd.read_csv(exported_path)
    assert list(dataframe.columns) == _EXPECTED_COLUMNS
    assert dataframe.iloc[0]["Nom"] == sample_restaurant.name
    assert dataframe.iloc[1]["Instagram"] == "https://www.instagram.com/cafeducoin/"


def test_excel_exporter_writes_expected_columns_and_adds_extension(
    tmp_path: Path, sample_restaurant: Restaurant
) -> None:
    destination = tmp_path / "restaurants"

    exported_path = ExcelExporter().export(_sample_restaurants(sample_restaurant), destination)

    assert exported_path == tmp_path / "restaurants.xlsx"
    dataframe = pd.read_excel(exported_path)
    assert list(dataframe.columns) == _EXPECTED_COLUMNS
    assert dataframe.iloc[0]["Nom"] == sample_restaurant.name


def test_csv_exporter_does_not_duplicate_extension(
    tmp_path: Path, sample_restaurant: Restaurant
) -> None:
    destination = tmp_path / "restaurants.csv"

    exported_path = CsvExporter().export([sample_restaurant], destination)

    assert exported_path == destination
