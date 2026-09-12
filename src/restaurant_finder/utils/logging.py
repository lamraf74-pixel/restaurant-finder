"""Configuration du logging applicatif."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from rich.logging import RichHandler

_FILE_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_FILE_LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

#: Bibliothèques HTTP "classiques" : intéressantes en `--verbose` (montre les
#: requêtes envoyées), donc seulement calmées quand `verbose` est False.
_NOISY_LOGGERS_UNLESS_VERBOSE = ("urllib3", "requests", "ddgs", "httpx", "httpcore")

#: Sous-composants Rust exposés par le backend HTTP de `ddgs` (`primp`) :
#: handshake TLS, résolution DNS, framing HTTP/2, cookies bas niveau. Jamais
#: utile pour diagnostiquer l'application elle-même (juste du bruit massif :
#: des centaines de lignes pour une seule requête) — coupés systématiquement,
#: même en `--verbose`.
_ALWAYS_NOISY_LOGGERS = ("primp", "rustls", "h2", "hickory_net", "hickory_proto", "cookie_store")


def setup_logging(
    verbose: bool = False,
    log_file: Path | None = None,
    log_file_enabled: bool = True,
    log_file_max_bytes: int = 5_000_000,
    log_file_backup_count: int = 3,
) -> None:
    """Configure un logging homogène et lisible sur toute l'application.

    Deux sorties, avec des niveaux indépendants :

    - **Console** (Rich) : INFO par défaut, DEBUG si `verbose`. C'est ce que
      l'utilisateur voit en direct.
    - **Fichier** (`log_file`, ex: `restaurant-finder.log`) : toujours DEBUG,
      quel que soit `verbose`. Permet de comprendre après coup pourquoi une
      recherche a échoué, sans avoir à relancer en mode debug.

    Args:
        verbose: si True, active le niveau DEBUG sur la console (sinon INFO).
        log_file: chemin du fichier de log. Ignoré si `log_file_enabled` est False.
        log_file_enabled: active/désactive l'écriture du fichier de log.
        log_file_max_bytes: taille max avant rotation du fichier de log.
        log_file_backup_count: nombre de fichiers de log archivés conservés.
    """

    console_handler = RichHandler(rich_tracebacks=True, show_path=verbose)
    console_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    handlers: list[logging.Handler] = [console_handler]

    if log_file_enabled:
        file_path = log_file or Path("restaurant-finder.log")
        file_handler = _build_file_handler(
            file_path, max_bytes=log_file_max_bytes, backup_count=log_file_backup_count
        )
        if file_handler is not None:
            handlers.append(file_handler)

    # Niveau racine permissif (DEBUG) : le filtrage effectif se fait au niveau
    # de chaque handler (console vs fichier), pas ici.
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(message)s",
        datefmt="[%X]",
        handlers=handlers,
        force=True,
    )

    # Bibliothèques tierces trop verbeuses.
    for noisy_logger in _ALWAYS_NOISY_LOGGERS:
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)
    if not verbose:
        for noisy_logger in _NOISY_LOGGERS_UNLESS_VERBOSE:
            logging.getLogger(noisy_logger).setLevel(logging.WARNING)


def _build_file_handler(
    file_path: Path, *, max_bytes: int, backup_count: int
) -> logging.Handler | None:
    """Construit le handler fichier, ou None si le répertoire est inaccessible.

    Un log fichier illisible ne doit jamais empêcher l'application de
    démarrer : on se contente alors de l'affichage console.
    """

    try:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            file_path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
    except OSError:
        return None

    handler.setLevel(logging.DEBUG)
    handler.setFormatter(logging.Formatter(_FILE_LOG_FORMAT, datefmt=_FILE_LOG_DATE_FORMAT))
    return handler
