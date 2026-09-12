"""Tests de la couche CLI (validation des arguments, sans appel réseau)."""

from __future__ import annotations

from typing import Any

import pytest
from typer.testing import CliRunner

import restaurant_finder.cli as cli_module
from restaurant_finder.cli import app
from restaurant_finder.domain.models import Restaurant

runner = CliRunner()


def test_help_lists_search_command() -> None:
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "search" in result.output


def test_version_flag_prints_version_and_exits() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert "restaurant-finder" in result.output


def test_search_help_lists_cuisine_and_include_chains() -> None:
    result = runner.invoke(app, ["search", "--help"])

    assert result.exit_code == 0
    assert "--cuisine" in result.output
    assert "--include-chains" in result.output
    assert "bistro" in result.output
    assert "a_verifier" in result.output


def test_search_rejects_unknown_category() -> None:
    result = runner.invoke(app, ["search", "Lyon", "--category", "brasserie"])

    assert result.exit_code == 1
    assert "brasserie" in result.output


def test_search_rejects_unknown_format() -> None:
    result = runner.invoke(app, ["search", "Lyon", "--format", "pdf"])

    assert result.exit_code == 1
    assert "pdf" in result.output


def test_search_requires_city_or_near() -> None:
    result = runner.invoke(app, ["search"])

    assert result.exit_code == 1
    assert "--near" in result.output


def test_search_rejects_invalid_near_coordinates() -> None:
    result = runner.invoke(app, ["search", "--near", "pas-des-coordonnees"])

    assert result.exit_code == 1
    assert "invalide" in result.output.lower()


def test_search_help_lists_fresh_flag() -> None:
    result = runner.invoke(app, ["search", "--help"])

    assert result.exit_code == 0
    assert "--fresh" in result.output


class _RaisingService:
    """Simule un `RestaurantFinderService` dont la recherche échoue."""

    def __init__(self, error: BaseException) -> None:
        self._error = error

    def find_restaurants(self, **kwargs: Any) -> list[Restaurant]:
        raise self._error


def test_search_handles_keyboard_interrupt_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli_module, "build_service", lambda *a, **k: _RaisingService(KeyboardInterrupt())
    )

    result = runner.invoke(app, ["search", "Lyon"])

    assert result.exit_code == 130
    assert "Traceback" not in result.output
    assert "interrompue" in result.output.lower()


def test_search_handles_unexpected_exception_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli_module,
        "build_service",
        lambda *a, **k: _RaisingService(RuntimeError("boom inattendu")),
    )

    result = runner.invoke(app, ["search", "Lyon"])

    assert result.exit_code == 1
    assert "Traceback" not in result.output
    assert "inattendue" in result.output.lower()
