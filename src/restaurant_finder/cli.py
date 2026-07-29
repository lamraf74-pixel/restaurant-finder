"""Interface en ligne de commande (Typer).

Cette couche ne contient aucune logique métier : elle se contente de
parser les arguments, d'appeler `RestaurantFinderService` et d'afficher
le résultat. Elle pourrait être remplacée demain par une API FastAPI
sans modifier une seule ligne des autres couches.
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from restaurant_finder import __version__
from restaurant_finder.bootstrap import build_service
from restaurant_finder.config import DEFAULT_CATEGORY_LABELS, get_settings
from restaurant_finder.domain.models import Restaurant
from restaurant_finder.exceptions import RestaurantFinderError
from restaurant_finder.export import EXPORTERS
from restaurant_finder.services.restaurant_finder_service import RestaurantFinderService
from restaurant_finder.utils.logging import setup_logging

app = typer.Typer(
    name="restaurant-finder",
    help="Recherche des restaurants (OpenStreetMap) et retrouve leur profil Instagram.",
    add_completion=False,
    no_args_is_help=True,
)
console = Console()


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"restaurant-finder {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool | None = typer.Option(
        None,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Affiche la version et quitte.",
    ),
) -> None:
    """Restaurant Finder — recherche et export de restaurants."""


@app.command()
def search(
    city: str = typer.Argument(..., help="Ville à rechercher, ex : 'Lyon'."),
    categories: list[str] = typer.Option(
        [],
        "--category",
        "-c",
        help=(
            "Catégorie(s) OSM à inclure parmi : "
            f"{', '.join(DEFAULT_CATEGORY_LABELS)}. Option répétable. Par défaut : toutes."
        ),
    ),
    limit: int | None = typer.Option(
        None, "--limit", "-l", min=1, help="Nombre maximal de restaurants à retourner."
    ),
    output: Path = typer.Option(
        Path("output") / "restaurants",
        "--output",
        "-o",
        help="Chemin de sortie sans extension, ex : 'output/lyon'.",
    ),
    formats: list[str] = typer.Option(
        ["csv", "xlsx"],
        "--format",
        "-f",
        help=f"Format(s) d'export parmi : {', '.join(EXPORTERS)}. Option répétable.",
    ),
    no_instagram: bool = typer.Option(
        False,
        "--no-instagram",
        help="Désactive la recherche du profil Instagram (plus rapide).",
    ),
    only_with_instagram: bool = typer.Option(
        False,
        "--only-with-instagram",
        help="N'exporte que les établissements pour lesquels un Instagram a été trouvé.",
    ),
    include_chains: bool = typer.Option(
        False,
        "--include-chains",
        help=(
            "Inclut les grandes enseignes / franchises (McDo, Subway, Burger King...). "
            "Par défaut elles sont exclues."
        ),
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Active les logs détaillés (debug)."
    ),
) -> None:
    """Recherche les restaurants d'une ville et exporte les résultats en CSV/Excel."""

    setup_logging(verbose=verbose)

    if no_instagram and only_with_instagram:
        console.print(
            "[bold red]Options incompatibles :[/bold red] "
            "--no-instagram et --only-with-instagram ne peuvent pas être utilisés ensemble."
        )
        raise typer.Exit(code=1)

    _validate_choices("catégorie", categories, allowed=set(DEFAULT_CATEGORY_LABELS))
    _validate_choices("format", formats, allowed=set(EXPORTERS))

    settings = get_settings()
    service = build_service(settings, enable_instagram=not no_instagram)

    console.print(f"[bold]Recherche des établissements à[/bold] [cyan]{city}[/cyan]...")
    if not include_chains:
        console.print("[dim]Filtre actif : enseignes / franchises exclues.[/dim]")

    try:
        with console.status("Interrogation d'OpenStreetMap (Overpass)..."):
            restaurants = service.find_restaurants(
                city=city,
                categories=categories or None,
                limit=limit,
                enrich_instagram=False,
                exclude_chains=not include_chains,
            )
    except RestaurantFinderError as exc:
        console.print(f"[bold red]Erreur :[/bold red] {exc}")
        raise typer.Exit(code=1) from None

    if not restaurants:
        console.print("[yellow]Aucun établissement trouvé pour cette recherche.[/yellow]")
        raise typer.Exit(code=0)

    console.print(
        f"[green]{len(restaurants)} établissement(s) indépendant(s) retenu(s).[/green]"
        if not include_chains
        else f"[green]{len(restaurants)} établissement(s) trouvé(s).[/green]"
    )

    if not no_instagram:
        restaurants = _enrich_with_progress(service, restaurants)
        with_instagram = sum(1 for item in restaurants if item.instagram_url)
        console.print(
            f"[magenta]{with_instagram}/{len(restaurants)} profil(s) Instagram trouvé(s).[/magenta]"
        )

        if only_with_instagram:
            restaurants = [item for item in restaurants if item.instagram_url]
            if not restaurants:
                console.print(
                    "[yellow]Aucun profil Instagram trouvé : rien à exporter.[/yellow]"
                )
                raise typer.Exit(code=0)
            console.print(
                f"[green]Export filtré : {len(restaurants)} établissement(s) avec Instagram.[/green]"
            )

    _print_summary_table(restaurants)

    exporters = [EXPORTERS[fmt] for fmt in formats]
    try:
        exported_paths = service.export(restaurants, exporters, output)
    except RestaurantFinderError as exc:
        console.print(f"[bold red]Erreur lors de l'export :[/bold red] {exc}")
        raise typer.Exit(code=1) from None

    console.print("\n[bold green]Export terminé :[/bold green]")
    for path in exported_paths:
        console.print(f"  • {path}")


def _validate_choices(label: str, values: list[str], allowed: set[str]) -> None:
    invalid = set(values) - allowed
    if invalid:
        console.print(f"[bold red]{label.capitalize()}(s) inconnue(s) : {', '.join(invalid)}[/bold red]")
        console.print(f"Valeurs autorisées : {', '.join(sorted(allowed))}")
        raise typer.Exit(code=1)


def _enrich_with_progress(
    service: RestaurantFinderService, restaurants: list[Restaurant]
) -> list[Restaurant]:
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task("Recherche des profils Instagram...", total=len(restaurants))

        def on_progress(done: int, total: int) -> None:
            progress.update(task_id, completed=done)

        restaurants = service.enrich_with_instagram(restaurants, on_progress=on_progress)

    return restaurants


def _print_summary_table(restaurants: list[Restaurant]) -> None:
    table = Table(title="Aperçu des résultats", show_lines=False)
    table.add_column("Nom", style="bold")
    table.add_column("Catégorie")
    table.add_column("Ville")
    table.add_column("Instagram", style="magenta")

    preview_count = min(len(restaurants), 15)
    for restaurant in restaurants[:preview_count]:
        table.add_row(
            restaurant.name,
            restaurant.category,
            restaurant.city,
            restaurant.instagram_url or "—",
        )

    console.print(table)
    if len(restaurants) > preview_count:
        console.print(f"[dim]... et {len(restaurants) - preview_count} de plus.[/dim]")


if __name__ == "__main__":
    app()
