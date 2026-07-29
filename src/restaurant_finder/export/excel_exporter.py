"""Export des résultats au format Excel (.xlsx)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from restaurant_finder.domain.models import Restaurant
from restaurant_finder.exceptions import ExportError
from restaurant_finder.export.base import Exporter

_COLUMN_WIDTHS = {"Nom": 32, "Instagram": 38, "Adresse": 34, "Ville": 18, "Catégorie": 16}


class ExcelExporter(Exporter):
    """Exporte une liste de restaurants vers un classeur Excel (.xlsx)."""

    file_extension = "xlsx"

    def export(self, restaurants: list[Restaurant], destination: Path) -> Path:
        destination = self.with_extension(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)

        rows = [restaurant.to_export_row() for restaurant in restaurants]
        dataframe = pd.DataFrame(rows, columns=list(_COLUMN_WIDTHS.keys()))

        try:
            with pd.ExcelWriter(destination, engine="openpyxl") as writer:
                dataframe.to_excel(writer, index=False, sheet_name="Restaurants")
                self._autosize_columns(writer)
        except OSError as exc:
            raise ExportError(f"Impossible d'écrire le fichier Excel {destination} : {exc}") from exc

        return destination

    @staticmethod
    def _autosize_columns(writer: pd.ExcelWriter) -> None:
        worksheet = writer.sheets["Restaurants"]
        for index, width in enumerate(_COLUMN_WIDTHS.values(), start=1):
            column_letter = worksheet.cell(row=1, column=index).column_letter
            worksheet.column_dimensions[column_letter].width = width
