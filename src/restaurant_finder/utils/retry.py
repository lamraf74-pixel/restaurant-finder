"""Aide générique pour retenter une opération réseau instable (retry + backoff).

Centraliser cette logique permet d'avoir un comportement homogène (nombre
d'essais, délai croissant, logs) sur tous les appels réseau de l'application
(Overpass, Nominatim, scraping de site web, DuckDuckGo, profil Instagram...),
au lieu de dupliquer un `try/except` légèrement différent à chaque endroit.

Volontairement une fonction (pas un décorateur) : elle s'utilise autour d'un
appel précis (ex: uniquement la requête HTTP brute, pas le parsing qui suit),
ce qui laisse à l'appelant le contrôle fin de ce qui doit être retenté.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterable
from typing import TypeVar

T = TypeVar("T")

logger = logging.getLogger(__name__)

#: Nombre d'essais minimal : même si `attempts` est mal configuré (0 ou négatif),
#: on tente au moins une fois.
_MIN_ATTEMPTS = 1


def call_with_retry(
    func: Callable[[], T],
    *,
    operation: str,
    attempts: int = 3,
    base_delay: float = 1.0,
    backoff_factor: float = 2.0,
    retry_on: Iterable[type[BaseException]] = (Exception,),
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Exécute `func()`, en retentant en cas d'échec transitoire.

    Args:
        func: opération à exécuter (sans argument ; utiliser une closure/lambda
            pour capturer les paramètres réels).
        operation: description courte utilisée dans les logs, ex:
            "Géocodage Nominatim de 'Lyon'".
        attempts: nombre total de tentatives (1 = pas de retry).
        base_delay: délai (secondes) avant le 2e essai.
        backoff_factor: multiplicateur appliqué à chaque nouvel échec
            (backoff exponentiel : `base_delay * backoff_factor**(n-1)`).
        retry_on: types d'exceptions considérés comme transitoires (donc
            retentés). Toute autre exception est immédiatement relevée.
        sleep: fonction d'attente (injectable dans les tests).

    Returns:
        Le résultat de `func()` dès qu'un essai réussit.

    Raises:
        La dernière exception rencontrée, si tous les essais échouent.
    """

    retry_exceptions = tuple(retry_on)
    total_attempts = max(_MIN_ATTEMPTS, attempts)
    last_exc: BaseException | None = None

    for attempt in range(1, total_attempts + 1):
        logger.debug("%s : tentative %d/%d...", operation, attempt, total_attempts)
        try:
            result = func()
        except retry_exceptions as exc:
            last_exc = exc
            if attempt >= total_attempts:
                logger.error(
                    "%s : abandon après %d tentative(s) — %s.",
                    operation,
                    attempt,
                    exc,
                )
                break
            delay = base_delay * (backoff_factor ** (attempt - 1))
            logger.warning(
                "%s : échec tentative %d/%d (%s) — nouvel essai dans %.1fs.",
                operation,
                attempt,
                total_attempts,
                exc,
                delay,
            )
            sleep(delay)
            continue
        else:
            if attempt > 1:
                logger.info("%s : succès après %d tentative(s).", operation, attempt)
            else:
                logger.debug("%s : succès.", operation)
            return result

    assert last_exc is not None  # garanti par la boucle ci-dessus (attempts >= 1)
    raise last_exc
