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
from restaurant_finder.bootstrap import build_location_parser, build_service
from restaurant_finder.config import DEFAULT_CATEGORY_LABELS, get_settings
from restaurant_finder.domain.models import Restaurant
from restaurant_finder.exceptions import LocationParsingError, RestaurantFinderError
from restaurant_finder.export import EXPORTERS
from restaurant_finder.export.csv_exporter import CsvExporter
from restaurant_finder.filtering.cuisine_filter import DEFAULT_CUISINES, parse_cuisine_values
from restaurant_finder.geocoding.geo_math import PointQuery
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
    city: str | None = typer.Argument(
        None,
        help="Ville à rechercher, ex : 'Lyon'. Optionnel si --near est utilisé.",
    ),
    near: list[str] = typer.Option(
        [],
        "--near",
        "-n",
        help=(
            "Lieu \"pingué\" sur Google Maps : coordonnées collées ('45.9177, 6.1319') "
            "ou lien Google Maps complet. Option répétable pour étendre la recherche "
            "à plusieurs lieux (les résultats sont fusionnés)."
        ),
    ),
    radius: float = typer.Option(
        800.0,
        "--radius",
        "-r",
        min=10,
        help="Rayon de recherche en mètres autour de chaque --near (défaut : 800m).",
    ),
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
            "Inclut les chaînes / franchises (tout établissement OSM avec un tag "
            "`brand` non vide, plus les enseignes connues). Par défaut elles sont exclues."
        ),
    ),
    cuisine: str | None = typer.Option(
        None,
        "--cuisine",
        help=(
            "Filtre optionnel sur le tag OSM `cuisine` : valeurs séparées par "
            "des virgules (ex: bistro,pizza). Sans cette option, aucun filtre "
            "cuisine n'est appliqué. Avec l'option, les établissements sans "
            f"tag cuisine sont exclus. Exemples courants : {', '.join(DEFAULT_CUISINES)}."
        ),
    ),
    max_followers: int = typer.Option(
        1000,
        "--max-followers",
        min=1,
        help="Exclut les comptes Instagram avec au moins ce nombre de followers (défaut : 1000).",
    ),
    keep_unknown_followers: bool = typer.Option(
        False,
        "--keep-unknown-followers",
        help=(
            "Garde un Instagram même si le nombre de followers n'a pas pu être lu. "
            "Par défaut ces comptes sont exclus."
        ),
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Active les logs détaillés (debug)."
    ),
) -> None:
    """Recherche les restaurants d'une ville et exporte les résultats en CSV/Excel.

    Seules les associations Instagram de confiance Élevé restent dans le
    fichier principal. Moyen et Faible sont sauvegardées dans
    ``a_verifier.csv`` (même dossier que ``--output``) pour vérification
    manuelle.
    """

    setup_logging(verbose=verbose)

    if no_instagram and only_with_instagram:
        console.print(
            "[bold red]Options incompatibles :[/bold red] "
            "--no-instagram et --only-with-instagram ne peuvent pas être utilisés ensemble."
        )
        raise typer.Exit(code=1)

    if not city and not near:
        console.print(
            "[bold red]Précise une ville[/bold red] (ex: 'Lyon') "
            "[bold red]ou au moins un lieu[/bold red] avec --near."
        )
        raise typer.Exit(code=1)

    _validate_choices("catégorie", categories, allowed=set(DEFAULT_CATEGORY_LABELS))
    _validate_choices("format", formats, allowed=set(EXPORTERS))

    settings = get_settings()
    settings.instagram_max_followers = max_followers
    settings.instagram_exclude_unknown_followers = not keep_unknown_followers

    near_points: list[PointQuery] = []
    if near:
        location_parser = build_location_parser(settings)
        for raw_location in near:
            try:
                latitude, longitude = location_parser.parse(raw_location)
            except LocationParsingError as exc:
                console.print(f"[bold red]Lieu invalide ({raw_location!r}) :[/bold red] {exc}")
                raise typer.Exit(code=1) from None
            near_points.append(PointQuery(latitude, longitude, radius))

    service = build_service(settings, enable_instagram=not no_instagram)

    if city:
        console.print(f"[bold]Recherche des établissements à[/bold] [cyan]{city}[/cyan]...")
    if near_points:
        points_label = ", ".join(f"({p.latitude:.5f}, {p.longitude:.5f})" for p in near_points)
        console.print(
            f"[bold]Recherche autour de[/bold] [cyan]{points_label}[/cyan] "
            f"[bold](rayon {radius:.0f}m)[/bold]..."
        )
    if not include_chains:
        console.print(
            "[dim]Filtre actif : chaînes exclues (tag OSM brand + enseignes connues).[/dim]"
        )
    cuisine_values = parse_cuisine_values(cuisine)
    if cuisine_values:
        console.print(
            f"[dim]Filtre cuisine : {', '.join(cuisine_values)} "
            f"(sans tag cuisine -> exclu).[/dim]"
        )
    if not no_instagram:
        console.print(
            f"[dim]Filtre Instagram : moins de {max_followers} followers ; "
            f"confiance Moyen/Faible -> output/a_verifier.csv.[/dim]"
        )

    try:
        with console.status("Interrogation d'OpenStreetMap (Overpass)..."):
            restaurants = service.find_restaurants(
                cities=[city] if city else None,
                near_points=near_points or None,
                categories=categories or None,
                limit=limit,
                enrich_instagram=False,
                exclude_chains=not include_chains,
                cuisines=cuisine_values,
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

        restaurants, to_review = RestaurantFinderService.split_by_instagram_confidence(
            restaurants
        )
        if to_review:
            console.print(
                f"[yellow]{len(to_review)} association(s) Instagram Moyen/Faible "
                f"écartée(s) du fichier principal -> a_verifier.csv.[/yellow]"
            )

        if only_with_instagram:
            restaurants = [item for item in restaurants if item.instagram_url]
            if not restaurants and not to_review:
                console.print(
                    "[yellow]Aucun profil Instagram trouvé : rien à exporter.[/yellow]"
                )
                raise typer.Exit(code=0)
            if restaurants:
                console.print(
                    f"[green]Export filtré : {len(restaurants)} établissement(s) "
                    f"avec Instagram (Élevé).[/green]"
                )
    else:
        to_review = []

    if not restaurants and not to_review:
        console.print("[yellow]Aucun établissement à exporter.[/yellow]")
        raise typer.Exit(code=0)

    if restaurants:
        _print_summary_table(restaurants)

    exporters = [EXPORTERS[fmt] for fmt in formats]
    try:
        exported_paths: list[Path] = []
        if restaurants:
            exported_paths.extend(service.export(restaurants, exporters, output))
        if to_review:
            review_path = output.parent / "a_verifier"
            exported_paths.append(CsvExporter().export(to_review, review_path))
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


@app.command()
def ui(
    host: str = typer.Option("127.0.0.1", "--host", help="Adresse d'écoute du serveur local."),
    port: int = typer.Option(8765, "--port", "-p", help="Port du serveur local."),
    no_browser: bool = typer.Option(
        False, "--no-browser", help="N'ouvre pas automatiquement le navigateur."
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v", help="Active les logs détaillés (debug)."
    ),
) -> None:
    """Lance le panel web : carte interactive pour lancer des recherches sans commande."""

    import threading
    import webbrowser

    import uvicorn

    from restaurant_finder.webapp.server import create_app

    setup_logging(verbose=verbose)

    settings = get_settings()
    web_app = create_app(settings)

    url = f"http://{host}:{port}"
    console.print(f"[bold green]Panel disponible sur[/bold green] [cyan]{url}[/cyan]")
    console.print("[dim]Ctrl+C pour arrêter le serveur.[/dim]")

    if not no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    uvicorn.run(web_app, host=host, port=port, log_level="warning" if not verbose else "info")


def _print_summary_table(restaurants: list[Restaurant]) -> None:
    table = Table(title="Aperçu des résultats", show_lines=False)
    table.add_column("Nom", style="bold")
    table.add_column("Catégorie")
    table.add_column("Ville")
    table.add_column("Instagram", style="magenta")
    table.add_column("Confiance")

    preview_count = min(len(restaurants), 15)
    for restaurant in restaurants[:preview_count]:
        table.add_row(
            restaurant.name,
            restaurant.category,
            restaurant.city,
            restaurant.instagram_handle or "—",
            restaurant.instagram_confidence.value if restaurant.instagram_confidence else "—",
        )

    console.print(table)
    if len(restaurants) > preview_count:
        console.print(f"[dim]... et {len(restaurants) - preview_count} de plus.[/dim]")


if __name__ == "__main__":
    app()
