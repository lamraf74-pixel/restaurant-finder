# Restaurant Finder

Outil en ligne de commande qui recherche automatiquement les restaurants
(et cafés, bars, fast-foods...) d'une ville à partir des données libres
**OpenStreetMap**, tente de retrouver le **profil Instagram officiel** de
chaque établissement, puis exporte le résultat en **CSV** et **Excel**.

Colonnes exportées : `Nom`, `Instagram`, `Adresse`, `Ville`, `Catégorie`.

## Sommaire

- [Architecture](#architecture)
- [Installation](#installation)
- [Utilisation](#utilisation)
- [Configuration](#configuration)
- [Limites connues](#limites-connues)
- [Développement](#développement)

## Architecture

Le projet suit une architecture en couches, où le cœur métier ne dépend
d'aucun détail technique. Chaque brique externe (source de données,
moteur de recherche, format d'export) est isolée derrière une interface
abstraite, ce qui permet de la remplacer ou d'en ajouter une nouvelle sans
toucher au reste du code.

```
Ville (CLI)
   │
   ▼
RestaurantFinderService  ──────────────► Exporters (CSV, Excel, ...)
   │        │
   │        └── InstagramFinder ──► SearchProvider (DuckDuckGo, ...)
   │                                    + matching flou (rapidfuzz)
   ▼
RestaurantSource (Overpass) ──► NominatimGeocoder (ville → bbox)
```

```
src/restaurant_finder/
├── cli.py                     # Présentation (Typer + Rich) — aucune logique métier
├── bootstrap.py                # Composition root : câblage des dépendances
├── config.py                   # Configuration (pydantic-settings, variables RF_*)
├── exceptions.py                # Exceptions métier centralisées
├── domain/
│   └── models.py                # Restaurant, BoundingBox (pydantic)
├── geocoding/
│   └── nominatim_client.py      # Ville -> zone géographique (Nominatim)
├── sources/
│   ├── base.py                  # Interface RestaurantSource
│   └── overpass_source.py       # Implémentation OpenStreetMap / Overpass
├── enrichment/
│   ├── matching.py               # Score de similarité nom ↔ résultat web (rapidfuzz)
│   ├── instagram_finder.py       # Orchestration de la recherche Instagram
│   └── search_providers/
│       ├── base.py                # Interface SearchProvider
│       └── duckduckgo_provider.py # Implémentation DuckDuckGo (scraping HTML)
├── export/
│   ├── base.py                   # Interface Exporter
│   ├── csv_exporter.py
│   └── excel_exporter.py
├── services/
│   └── restaurant_finder_service.py  # Orchestration du pipeline complet
├── cache/
│   └── file_cache.py              # Cache disque (TTL) pour limiter les requêtes réseau
├── http/
│   └── client.py                  # Session HTTP partagée (retries, User-Agent)
└── utils/
    ├── text.py                    # Normalisation de texte
    └── logging.py                 # Configuration du logging (Rich)
```

### Pourquoi cette architecture ?

- **Testabilité** : chaque couche se teste indépendamment (mock des
  interfaces `RestaurantSource`, `SearchProvider`, `Exporter`).
- **Évolutivité** : ajouter une source de données (Google Places), un
  fournisseur de recherche plus fiable (SerpApi), ou un format d'export
  (JSON) ne nécessite qu'une nouvelle classe implémentant l'interface
  correspondante — zéro régression sur l'existant.
- **Remplaçabilité de la CLI** : `cli.py` ne fait qu'appeler
  `RestaurantFinderService`. Une future API REST (FastAPI) pourrait
  réutiliser exactement le même service métier.

### Choix techniques

| Besoin | Choix | Justification |
|---|---|---|
| CLI | Typer + Rich | Typage fort, aide auto-générée, sorties lisibles (tableaux, barres de progression) |
| Données restaurants | OpenStreetMap (Overpass API) | Gratuit, sans clé API, données ouvertes |
| Géocodage | Nominatim | Service OSM officiel pour convertir un nom de ville en zone géographique |
| Recherche Instagram | DuckDuckGo (scraping HTML) + rapidfuzz | Aucune API de recherche web gratuite n'existe ; approche heuristique isolée derrière une interface remplaçable |
| Validation des données | Pydantic | Modèles typés et auto-validés, sérialisation simple |
| Export | pandas + openpyxl | Un seul DataFrame, deux formats de sortie cohérents |
| Configuration | pydantic-settings | Variables d'environnement / `.env` sans configuration manuelle |
| Cache | Fichiers JSON + TTL maison | Évite de re-solliciter Nominatim/Overpass/DuckDuckGo ; pas de dépendance supplémentaire |

## Installation

Prérequis : **Python 3.10+**.

```bash
git clone <votre-repo> restaurant-finder
cd restaurant-finder
python -m venv .venv
.venv\Scripts\activate        # Windows (PowerShell : .venv\Scripts\Activate.ps1)
# source .venv/bin/activate   # macOS / Linux

pip install -e ".[dev]"
```

> **Windows / PowerShell** : si les caractères accentués s'affichent mal
> dans le terminal, exécutez `chcp 65001` (ou `$env:PYTHONUTF8=1`) avant
> de lancer la commande — c'est un réglage d'encodage du terminal, pas un
> bug de l'application.

## Utilisation

```bash
# Recherche basique : restaurants + cafés + bars... de Lyon, export CSV + Excel
restaurant-finder search "Lyon"

# Filtrer par catégorie (répétable) et limiter le nombre de résultats
restaurant-finder search "Bordeaux" --category restaurant --category cafe --limit 50

# Choisir le chemin et le(s) format(s) de sortie
restaurant-finder search "Nantes" --output output/nantes --format csv --format xlsx

# Recherche rapide, sans enrichissement Instagram
restaurant-finder search "Marseille" --no-instagram

# Logs détaillés (debug)
restaurant-finder search "Nice" --verbose
```

Équivalent sans installation du script : `python -m restaurant_finder search "Lyon"`.

Catégories disponibles : `restaurant`, `cafe`, `fast_food`, `bar`, `pub`, `biergarten`.

## Configuration

Toute la configuration se surcharge via des variables d'environnement
préfixées par `RF_`, ou un fichier `.env` à la racine (voir
[`.env.example`](.env.example)). Exemples utiles :

- `RF_USER_AGENT` : identifiez-vous auprès de Nominatim (obligatoire selon leur politique d'usage).
- `RF_INSTAGRAM_SEARCH_DELAY_SECONDS` : espacement minimal entre les recherches Instagram.
- `RF_INSTAGRAM_MATCH_THRESHOLD` : seuil de confiance (0-100) pour valider un profil Instagram.
- `RF_CACHE_TTL_SECONDS` : durée de vie du cache local.

## Limites connues

- **Recherche Instagram heuristique** : il n'existe pas d'API de
  recherche web gratuite et officielle. Le `DuckDuckGoSearchProvider`
  scrape la page HTML publique de DuckDuckGo ; c'est un point de
  fragilité assumé (le HTML peut changer sans préavis) et volontairement
  isolé derrière l'interface `SearchProvider`, remplaçable par un
  fournisseur payant (SerpApi, Google Custom Search...) si besoin de
  fiabilité accrue.
- **Couverture des données** : dépend de la qualité du référencement
  OpenStreetMap sur la zone recherchée (certains établissements peuvent
  manquer ou avoir une adresse incomplète).
- **Respect des services tiers** : des délais et un cache sont appliqués
  par défaut pour rester raisonnable vis-à-vis de Nominatim, Overpass et
  DuckDuckGo. Ne pas les désactiver en usage intensif.
- **Disponibilité d'Overpass** : l'instance publique gratuite
  (`overpass-api.de`) est fortement sollicitée par toute la communauté
  OSM et répond parfois par des erreurs transitoires (`406`, `504`,
  timeouts), en particulier depuis une IP partagée (CI, VM, sandbox...).
  Le logiciel bascule alors automatiquement sur des miroirs de secours
  (`lz4.overpass-api.de`, `overpass.kumi.systems`). Si les trois échouent,
  ce n'est pas un bug : patientez quelques dizaines de secondes puis
  relancez la commande (le géocodage de la ville reste en cache).

## Développement

```bash
# Lancer les tests
pytest

# Linter
ruff check .

# Vérification de types
mypy
```

Structure de tests (`tests/`) : chaque couche technique (matching,
source Overpass, finder Instagram, exporteurs, CLI) est testée en
isolation grâce aux interfaces abstraites et au mocking des appels réseau.
