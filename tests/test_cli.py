"""Tests de la couche CLI (validation des arguments, sans appel réseau)."""

from __future__ import annotations

from typer.testing import CliRunner

from restaurant_finder.cli import app

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
