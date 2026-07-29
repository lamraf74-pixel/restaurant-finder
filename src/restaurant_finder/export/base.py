"""Interface abstraite d'un exporteur de résultats.

Ajouter un nouveau format d'export (JSON, Google Sheets, base de
données...) se fait en implémentant ce contrat, sans toucher au reste
de l'application (principe ouvert/fermé).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import ClassVar

from restaurant_finder.domain.models import Restaurant


class Exporter(ABC):
    """Contrat pour tout exporteur de résultats."""

    file_extension: ClassVar[str]

    @abstractmethod
    def export(self, restaurants: list[Restaurant], destination: Path) -> Path:
        """Écrit `restaurants` dans un fichier et retourne le chemin final."""
        raise NotImplementedError

    def with_extension(self, destination: Path) -> Path:
        """Garantit que `destination` porte bien l'extension attendue."""

        if destination.suffix.lower() == f".{self.file_extension}":
            return destination
        return destination.with_suffix(f".{self.file_extension}")
