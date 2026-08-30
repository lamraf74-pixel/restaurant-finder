"""Export des résultats au format CSV."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from restaurant_finder.domain.models import Restaurant
from restaurant_finder.exceptions import ExportError
from restaurant_finder.export.base import Exporter


class CsvExporter(Exporter):
    """Exporte une liste de restaurants vers un fichier CSV (UTF-8 avec BOM)."""

    file_extension = "csv"

    def export(self, restaurants: list[Restaurant], destination: Path) -> Path:
        destination = self.with_extension(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)

        rows = [restaurant.to_export_row() for restaurant in restaurants]
        dataframe = pd.DataFrame(
            rows, columns=["Nom", "Instagram", "Adresse", "Ville", "Catégorie", "Confiance"]
        )

        try:
            # encoding="utf-8-sig" pour qu'Excel affiche correctement les accents.
            dataframe.to_csv(destination, index=False, encoding="utf-8-sig")
        except OSError as exc:
            raise ExportError(f"Impossible d'écrire le CSV {destination} : {exc}") from exc

        return destination
