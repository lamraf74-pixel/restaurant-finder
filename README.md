# Restaurant Finder

Outil en ligne de commande qui recherche automatiquement les restaurants
(et cafés, bars, fast-foods...) d'une ville à partir des données libres
**OpenStreetMap**, tente de retrouver le **profil Instagram officiel** de
chaque établissement, puis exporte le résultat en **CSV** et **Excel**.

Colonnes exportées : `Nom`, `Instagram` (handle uniquement, ex. `bistrot_le_cerey`), `Adresse`, `Ville`, `Catégorie`.

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
Ville et/ou lieux "pingués" (CLI)
   │
   ▼
RestaurantFinderService  ──────────────► Exporters (CSV, Excel, ...)
   │        │
   │        └── InstagramFinder ──► SearchProvider (ddgs, ...)
   │                                    + matching flou (rapidfuzz)
   ▼
RestaurantSource (Overpass) ──► NominatimGeocoder (ville → bbox)
                            ──► LocationInputParser (coordonnées / lien Maps → point)
                            ──► geo_math (point + rayon → bbox, filtrage par distance)
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
│   ├── nominatim_client.py      # Ville <-> zone géographique (géocodage + reverse)
│   ├── geo_math.py               # Point + rayon -> bbox, distance à vol d'oiseau
│   └── location_parser.py        # Coordonnées / lien Google Maps -> (latitude, longitude)
├── sources/
│   ├── base.py                  # Interface RestaurantSource
│   └── overpass_source.py       # Implémentation OpenStreetMap / Overpass (ville et/ou points)
├── enrichment/
│   ├── matching.py               # Score de similarité nom ↔ résultat web (rapidfuzz)
│   ├── instagram_normalize.py    # URL/handle Instagram <-> forme canonique
│   ├── instagram_finder.py       # Recherche + vérification du candidat (anti faux-positifs)
│   ├── instagram_profile.py      # Lecture du vrai profil (nom, bio, followers)
│   └── search_providers/
│       ├── base.py                # Interface SearchProvider
│       └── ddgs_provider.py       # Implémentation via la librairie ddgs
├── filtering/
│   └── chain_filter.py           # Exclusion des grandes enseignes / franchises
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
├── webapp/
│   ├── server.py                  # Application FastAPI (routes /api/*)
│   ├── jobs.py                    # Recherches en arrière-plan + suivi de progression
│   ├── schemas.py                 # Modèles pydantic de l'API HTTP
│   └── static/                    # Page HTML/CSS/JS (carte Leaflet, aucun build)
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
| Panel web | FastAPI + Leaflet (JS vanilla) | Aucune étape de build, carte gratuite (OSM), même `RestaurantFinderService` que la CLI |
| Données restaurants | OpenStreetMap (Overpass API) | Gratuit, sans clé API, données ouvertes |
| Géocodage | Nominatim | Service OSM officiel pour convertir un nom de ville en zone géographique |
| Recherche Instagram | librairie `ddgs` + vérification du vrai profil | Gratuit, sans clé API ; les candidats sont vérifiés contre le nom complet / la bio réels du compte (pas seulement l'extrait de recherche), ce qui élimine la plupart des faux positifs |
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

### Panel web (recommandé, sans ligne de commande)

```bash
restaurant-finder ui
```

Ouvre automatiquement une page dans le navigateur avec une **carte interactive** :

- **Clique n'importe où sur la carte** pour ajouter un lieu de recherche (avec son propre rayon, ajustable).
- **Ajoute autant de villes que tu veux** dans le panneau de gauche.
- Combine villes et lieux cliqués dans la même recherche.
- Options avancées repliables (catégories, formats, filtre Instagram/followers, enseignes).
- Barre de progression en direct, tableau de résultats, boutons de téléchargement CSV/Excel.

Options : `--port 8080` (autre port), `--no-browser` (ne pas ouvrir automatiquement), `--host 0.0.0.0` (accessible depuis un autre appareil du réseau local).

### Ligne de commande

```bash
# Recherche basique : restaurants + cafés + bars... de Lyon, export CSV + Excel
restaurant-finder search "Lyon"

# Filtrer par catégorie (répétable) et limiter le nombre de résultats
restaurant-finder search "Bordeaux" --category restaurant --category cafe --limit 50

# Choisir le chemin et le(s) format(s) de sortie
restaurant-finder search "Nantes" --output output/nantes --format csv --format xlsx

# Recherche rapide, sans enrichissement Instagram
restaurant-finder search "Marseille" --no-instagram

# Uniquement les établissements avec un Instagram trouvé (cas d'usage principal)
restaurant-finder search "Nice" --limit 50 --only-with-instagram --output output/nice_instagram

# Inclure aussi les grandes enseignes (désactive le filtre franchises)
restaurant-finder search "Nice" --include-chains --limit 20

# Logs détaillés (debug)
restaurant-finder search "Nice" --verbose

# Recherche centrée sur un lieu "pingué" sur Google Maps (rayon 500m)
restaurant-finder search --near "43.6970, 7.2707" --radius 500

# Étendre la recherche à plusieurs lieux distincts (résultats fusionnés, sans doublon)
restaurant-finder search --near "43.6970, 7.2707" --near "45.7640, 4.8357" --radius 400

# Combiner une ville ET des points GPS précis
restaurant-finder search "Nice" --near "43.7009, 7.2761" --radius 600
```

### Rechercher autour d'un lieu précis (Google Maps)

1. Sur [Google Maps](https://maps.google.com), fais un **clic droit** sur l'endroit voulu.
2. Clique sur les coordonnées affichées en haut du menu (ex: `43.6970, 7.2707`) : elles sont copiées dans le presse-papier.
3. Colle-les dans `--near "43.6970, 7.2707"`.

Une URL Google Maps complète (copiée depuis la barre d'adresse, ou un lien court `maps.app.goo.gl/...`) fonctionne aussi directement avec `--near`.

`--near` est **répétable** : chaque lieu ajouté étend la zone de recherche. Les résultats de tous les lieux (et de la ville, si fournie) sont fusionnés et dédupliqués automatiquement. `--radius` (en mètres, 800 par défaut) s'applique à chaque `--near`.

Par défaut, les **grandes enseignes / franchises** (McDo, Subway, Burger King, Starbucks, etc.) sont **exclues** avant la recherche Instagram, pour ne garder que les indépendants.

Les comptes Instagram avec **1000 followers ou plus** sont aussi exclus (seuil réglable via `--max-followers`).

Équivalent sans installation du script : `python -m restaurant_finder search "Lyon"`.

Catégories disponibles : `restaurant`, `cafe`, `fast_food`, `bar`, `pub`, `biergarten`.

## Configuration

Toute la configuration se surcharge via des variables d'environnement
préfixées par `RF_`, ou un fichier `.env` à la racine (voir
[`.env.example`](.env.example)). Exemples utiles :

- `RF_USER_AGENT` : identifiez-vous auprès de Nominatim (obligatoire selon leur politique d'usage).
- `RF_INSTAGRAM_SEARCH_DELAY_SECONDS` : espacement minimal entre les recherches Instagram.
- `RF_INSTAGRAM_MATCH_THRESHOLD` : seuil de confiance (0-100) exigé sur le vrai profil pour valider un candidat.
- `RF_INSTAGRAM_MAX_PROFILE_CHECKS` : nombre max. de profils vérifiés par établissement (borne le coût réseau).
- `RF_INSTAGRAM_UNCONFIRMED_CITY_PENALTY` : pénalité appliquée si la ville n'est confirmée ni dans le handle ni dans la bio.
- `RF_CACHE_TTL_SECONDS` : durée de vie du cache local.

## Limites connues

- **Recherche Instagram heuristique, mais vérifiée** : il n'existe pas
  d'API Instagram officielle gratuite pour retrouver un compte à partir
  d'un nom. Le logiciel cherche des candidats via le web (`ddgs`), puis
  **vérifie chaque candidat contre son vrai profil** (nom complet +
  biographie, pas seulement l'extrait de recherche) avant de le retenir.
  Une pénalité supplémentaire s'applique si la ville du restaurant n'est
  confirmée nulle part (cas des enseignes régionales au nom quasi
  identique mais situées dans une autre ville). Le taux de trouvaille
  reste bon mais pas parfait ; en cas de doute, aucun compte n'est
  renvoyé plutôt qu'un mauvais candidat. L'option `--only-with-instagram`
  permet de n'exporter que les profils effectivement trouvés.
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
