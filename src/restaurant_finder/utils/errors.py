"""Formatage lisible des erreurs, pour l'affichage utilisateur et les logs.

Objectif : qu'une erreur réseau ou inattendue se traduise, à l'écran, par
une phrase compréhensible ("impossible de joindre le site web") plutôt que
par une exception Python brute — tout en conservant le détail complet
(traceback) dans le fichier de log pour un diagnostic ultérieur.
"""

from __future__ import annotations

import logging

import requests


def describe_exception(exc: BaseException) -> str:
    """Retourne une description courte et lisible de `exc`."""

    if isinstance(exc, requests.exceptions.Timeout):
        return "délai de connexion dépassé"
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "impossible de joindre le serveur"
    if isinstance(exc, requests.exceptions.HTTPError):
        return f"erreur HTTP ({exc})"
    if isinstance(exc, requests.exceptions.RequestException):
        return f"erreur réseau ({exc})"
    if isinstance(exc, KeyboardInterrupt):
        return "interrompu par l'utilisateur"
    message = str(exc).strip()
    return message or exc.__class__.__name__


def log_and_continue(
    logger_: logging.Logger,
    *,
    subject: str,
    action: str,
    exc: BaseException,
    level: int = logging.WARNING,
) -> None:
    """Loggue une erreur de façon lisible et permet au pipeline de continuer.

    Le message court (`subject`/`action`/cause résumée) est toujours visible
    (console + fichier de log). Le détail complet (traceback) n'est loggué
    qu'en DEBUG : il finit donc toujours dans le fichier de log, mais
    n'apparaît sur la console qu'en mode `--verbose`.
    """

    logger_.log(
        level,
        "Erreur sur %s : %s impossible (%s) — on continue.",
        subject,
        action,
        describe_exception(exc),
    )
    logger_.debug("Détail de l'erreur sur %s :", subject, exc_info=exc)
