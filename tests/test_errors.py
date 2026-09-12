"""Tests du formatage lisible des erreurs (`utils/errors.py`)."""

from __future__ import annotations

import logging

import pytest
import requests

from restaurant_finder.utils.errors import describe_exception, log_and_continue


def test_describe_exception_timeout() -> None:
    assert describe_exception(requests.exceptions.Timeout()) == "délai de connexion dépassé"


def test_describe_exception_connection_error() -> None:
    assert describe_exception(requests.exceptions.ConnectionError()) == (
        "impossible de joindre le serveur"
    )


def test_describe_exception_http_error() -> None:
    message = describe_exception(requests.exceptions.HTTPError("404 Not Found"))
    assert "404 Not Found" in message


def test_describe_exception_generic_exception_falls_back_to_str() -> None:
    assert describe_exception(ValueError("valeur invalide")) == "valeur invalide"


def test_describe_exception_without_message_falls_back_to_class_name() -> None:
    assert describe_exception(ValueError()) == "ValueError"


def test_log_and_continue_logs_short_message_and_full_detail(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("restaurant_finder.test_errors")

    with caplog.at_level(logging.DEBUG, logger=logger.name):
        try:
            raise requests.exceptions.ConnectionError("boom")
        except requests.exceptions.ConnectionError as exc:
            log_and_continue(
                logger,
                subject="le restaurant 'Le Petit Bistrot'",
                action="la recherche Instagram",
                exc=exc,
            )

    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning_records) == 1
    assert "Le Petit Bistrot" in warning_records[0].message
    assert "impossible de joindre le serveur" in warning_records[0].message
    assert "on continue" in warning_records[0].message

    debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert len(debug_records) == 1
    assert debug_records[0].exc_info is not None
