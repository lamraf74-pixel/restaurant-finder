"""Configuration du logging applicatif."""

from __future__ import annotations

import logging

from rich.logging import RichHandler


def setup_logging(verbose: bool = False) -> None:
    """Configure un logging homogène et lisible sur toute l'application.

    Args:
        verbose: si True, active le niveau DEBUG (sinon INFO).
    """

    level = logging.DEBUG if verbose else logging.INFO

    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True, show_path=verbose)],
        force=True,
    )

    # Bibliothèques tierces trop verbeuses : on les calme, sauf en mode verbose.
    if not verbose:
        for noisy_logger in ("urllib3", "requests"):
            logging.getLogger(noisy_logger).setLevel(logging.WARNING)
