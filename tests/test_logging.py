"""Tests de la configuration du logging (console Rich + fichier)."""

from __future__ import annotations

import logging
from pathlib import Path

from restaurant_finder.utils.logging import setup_logging


def _reset_logging() -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        handler.close()


def test_setup_logging_writes_debug_details_to_file_even_without_verbose(
    tmp_path: Path,
) -> None:
    log_file = tmp_path / "restaurant-finder.log"
    try:
        setup_logging(verbose=False, log_file=log_file)
        logger = logging.getLogger("restaurant_finder.test")
        logger.debug("détail de diagnostic")
        logger.info("message normal")
        for handler in logging.getLogger().handlers:
            handler.flush()

        assert log_file.exists()
        content = log_file.read_text(encoding="utf-8")
        assert "détail de diagnostic" in content
        assert "message normal" in content
    finally:
        _reset_logging()


def test_setup_logging_creates_missing_parent_directory(tmp_path: Path) -> None:
    log_file = tmp_path / "nested" / "dir" / "restaurant-finder.log"
    try:
        setup_logging(verbose=False, log_file=log_file)
        logging.getLogger("restaurant_finder.test").info("bonjour")
        for handler in logging.getLogger().handlers:
            handler.flush()

        assert log_file.exists()
    finally:
        _reset_logging()


def test_setup_logging_can_disable_file_logging(tmp_path: Path) -> None:
    log_file = tmp_path / "restaurant-finder.log"
    try:
        setup_logging(verbose=False, log_file=log_file, log_file_enabled=False)
        logging.getLogger("restaurant_finder.test").info("bonjour")

        assert not log_file.exists()
        assert len(logging.getLogger().handlers) == 1
    finally:
        _reset_logging()


def test_setup_logging_always_mutes_ddgs_rust_backend_noise(tmp_path: Path) -> None:
    """`primp`/`rustls`/`h2`/... (backend Rust de `ddgs`) : bruit énorme (TLS,

    DNS, framing HTTP/2) jamais utile pour diagnostiquer l'app — coupé même
    en `--verbose`, contrairement aux libs HTTP Python classiques.
    """

    log_file = tmp_path / "restaurant-finder.log"
    try:
        setup_logging(verbose=True, log_file=log_file)

        for noisy_logger in ("primp", "rustls", "h2", "hickory_net", "cookie_store"):
            assert logging.getLogger(noisy_logger).level == logging.WARNING
    finally:
        _reset_logging()


def test_setup_logging_console_handler_level_depends_on_verbose(tmp_path: Path) -> None:
    log_file = tmp_path / "restaurant-finder.log"
    try:
        setup_logging(verbose=False, log_file=log_file)
        console_handler = logging.getLogger().handlers[0]
        assert console_handler.level == logging.INFO

        setup_logging(verbose=True, log_file=log_file)
        console_handler = logging.getLogger().handlers[0]
        assert console_handler.level == logging.DEBUG
    finally:
        _reset_logging()
