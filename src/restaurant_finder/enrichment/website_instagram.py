"""Extraction d'un lien Instagram depuis le site web d'un établissement.

On ne scrape pas Instagram : on lit uniquement le HTML public du site
indiqué par le tag OSM `website` et on cherche un lien vers un profil.
"""

from __future__ import annotations

import logging

import requests

from restaurant_finder.enrichment.instagram_normalize import (
    extract_handles_from_text,
    to_profile_url,
)
from restaurant_finder.utils.retry import call_with_retry

logger = logging.getLogger(__name__)

#: Erreurs réseau transitoires : on retente ; une réponse HTTP d'erreur déjà
#: obtenue (404, 503...) n'est en revanche pas retentée ici.
_TRANSIENT_NETWORK_ERRORS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.ChunkedEncodingError,
)


def find_instagram_on_website(
    website_url: str,
    session: requests.Session,
    timeout: float,
    *,
    retry_attempts: int = 3,
    retry_base_delay: float = 1.0,
    retry_backoff_factor: float = 2.0,
) -> str | None:
    """Retourne l'URL de profil Instagram trouvée sur le site, ou None."""

    url = website_url.strip()
    if not url:
        return None

    if "://" not in url:
        url = f"https://{url}"

    try:
        response = call_with_retry(
            lambda: session.get(url, timeout=timeout, allow_redirects=True),
            operation=f"Scraping du site web {website_url!r}",
            attempts=retry_attempts,
            base_delay=retry_base_delay,
            backoff_factor=retry_backoff_factor,
            retry_on=_TRANSIENT_NETWORK_ERRORS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.debug("Scraping site web impossible pour %r : %s", website_url, exc)
        return None

    for handle in extract_handles_from_text(response.text):
        profile_url = to_profile_url(handle)
        if profile_url is not None:
            return profile_url

    return None
