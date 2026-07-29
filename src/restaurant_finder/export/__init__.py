from restaurant_finder.export.base import Exporter
from restaurant_finder.export.csv_exporter import CsvExporter
from restaurant_finder.export.excel_exporter import ExcelExporter

EXPORTERS: dict[str, Exporter] = {
    "csv": CsvExporter(),
    "xlsx": ExcelExporter(),
}

__all__ = ["Exporter", "CsvExporter", "ExcelExporter", "EXPORTERS"]
