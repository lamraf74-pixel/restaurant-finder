"""Signal de localisation hors de France dans un texte de profil Instagram.

Objectif : baisser la confiance (Élevé → Faible) quand la bio situe
clairement le compte à l'étranger, même si le nom du restaurant matche.

Précision d'abord (un restaurant français classé Faible à tort se revoit
à la main ; un Espagnol classé Élevé pollue l'export). On ne retient que
des indices de *lieu*, pas de cuisine :

- indicatif international autre que la France (ex. ``+34``, ``0039``) ;
- nom de pays (nom, pas l'adjectif : « Espagne » et pas « espagnole ») ;
- grande ville étrangère sans homonyme français courant ;
- drapeau emoji autre que 🇫🇷.

Un ancrage français (ville du restaurant, ``+33``, « France », 🇫🇷)
neutralise le signal : un bistrot à Perpignan qui cite Barcelone reste
français.
"""

from __future__ import annotations

import re

from restaurant_finder.utils.text import compact_text, normalize_text

#: Indicatifs du plan de numérotation français (métropole + outre-mer).
_FRENCH_DIAL_PREFIXES = (
    "33",
    "262",
    "508",
    "590",
    "594",
    "596",
    "681",
    "687",
    "689",
)

#: ``+34 932 00 00 00`` / ``00 39-06-123`` — au moins 6 chiffres après le préfixe.
_INTL_PHONE_RE = re.compile(r"(?<!\d)(?:\+|00)\s*((?:\d[\s.\-]*){6,15})")

#: Drapeaux de pays (hors France). Un 🇫🇷 dans le même texte annule ce signal.
_FOREIGN_FLAGS = (
    "🇪🇸",
    "🇮🇹",
    "🇵🇹",
    "🇩🇪",
    "🇧🇪",
    "🇨🇭",
    "🇬🇧",
    "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
    "🇳🇱",
    "🇦🇹",
    "🇮🇪",
    "🇱🇺",
    "🇦🇩",
    "🇲🇨",
    "🇬🇷",
    "🇲🇦",
    "🇹🇳",
    "🇩🇿",
    "🇺🇸",
    "🇨🇦",
    "🇧🇷",
    "🇲🇽",
    "🇦🇷",
    "🇨🇴",
    "🇯🇵",
    "🇨🇳",
    "🇰🇷",
    "🇹🇷",
    "🇵🇱",
    "🇷🇴",
    "🇨🇿",
    "🇸🇪",
    "🇳🇴",
    "🇩🇰",
    "🇫🇮",
    "🇹🇭",
    "🇻🇳",
)

#: Noms de pays (forme nominale, après normalisation). Pas d'adjectifs
#: (« espagnol », « italien ») qui apparaissent dans « cuisine espagnole ».
_FOREIGN_COUNTRIES = (
    "espagne",
    "espana",
    "spain",
    "italie",
    "italia",
    "italy",
    "portugal",
    "allemagne",
    "deutschland",
    "germany",
    "belgique",
    "belgium",
    "belgie",
    "suisse",
    "switzerland",
    "schweiz",
    "angleterre",
    "england",
    "royaume uni",
    "united kingdom",
    "pays bas",
    "netherlands",
    "nederland",
    "holland",
    "autriche",
    "austria",
    "osterreich",
    "grece",
    "greece",
    "irlande",
    "ireland",
    "maroc",
    "morocco",
    "tunisie",
    "tunisia",
    "algerie",
    "algeria",
    "etats unis",
    "united states",
    "usa",
    "mexique",
    "mexico",
    "bresil",
    "brazil",
    "brasil",
    "japon",
    "japan",
    "chine",
    "china",
    "thailande",
    "thailand",
    "turquie",
    "turkey",
    "pologne",
    "poland",
    "catalogne",
    "catalunya",
    "cataluna",
    "andalousie",
    "andalucia",
)

#: Grandes villes hors France, sans homonyme français usuel (pas Valence,
#: pas Porto / Porto-Vecchio, pas Genève — trop frontalier).
_FOREIGN_CITIES = (
    "barcelona",
    "barcelone",
    "madrid",
    "valencia",
    "sevilla",
    "seville",
    "malaga",
    "bilbao",
    "alicante",
    "zaragoza",
    "saragosse",
    "granada",
    "marbella",
    "ibiza",
    "mallorca",
    "majorque",
    "tenerife",
    "lisboa",
    "lisbonne",
    "lisbon",
    "roma",
    "rome",
    "milano",
    "milan",
    "napoli",
    "naples",
    "torino",
    "turin",
    "bologna",
    "bologne",
    "venezia",
    "venice",
    "venise",
    "firenze",
    "bruxelles",
    "brussels",
    "anvers",
    "antwerp",
    "bruges",
    "brugge",
    "amsterdam",
    "rotterdam",
    "berlin",
    "munich",
    "munchen",
    "hambourg",
    "hamburg",
    "francfort",
    "frankfurt",
    "cologne",
    "londres",
    "london",
    "manchester",
    "edinburgh",
    "edimbourg",
    "liverpool",
    "dublin",
    "zurich",
    "new york",
    "los angeles",
    "miami",
    "chicago",
    "boston",
    "bangkok",
    "casablanca",
    "marrakech",
    "marrakesh",
)

#: « spécialités d'Espagne » = origine culinaire, pas une adresse.
_CUISINE_ORIGIN_RE = re.compile(
    r"\b(?:cuisine|specialites?|gastronomie|saveurs?|recettes?|plats?)\s+"
    r"(?:d|de|du|des|from)\s+$"
)

_FRANCE_WORD_RE = re.compile(r"\bfrance\b")


def location_suggests_foreign_country(
    text: str,
    restaurant_city: str = "",
    restaurant_name: str = "",
) -> bool:
    """True si `text` situe clairement le compte hors de France.

    `restaurant_city` / `restaurant_name` évitent de pénaliser un
    établissement français dont le nom évoque un pays (ex. Thailand Food)
    ou dont la bio rappelle sa propre ville.
    """

    if not text or not text.strip():
        return False

    normalized = normalize_text(text)
    if _has_french_location_anchor(text, normalized, restaurant_city):
        return False
    return (
        _has_foreign_phone(text)
        or _has_foreign_flag(text)
        or _has_listed_phrase(normalized, _FOREIGN_COUNTRIES, restaurant_name)
        or _has_listed_phrase(normalized, _FOREIGN_CITIES, restaurant_name)
    )


def _has_french_location_anchor(original: str, normalized: str, restaurant_city: str) -> bool:
    if "🇫🇷" in original:
        return True
    if _FRANCE_WORD_RE.search(normalized):
        return True
    if _has_french_phone(original):
        return True
    city_token = compact_text(restaurant_city)
    return bool(city_token) and city_token in compact_text(original)


def _has_french_phone(text: str) -> bool:
    for match in _INTL_PHONE_RE.finditer(text):
        digits = re.sub(r"\D", "", match.group(1))
        if _starts_with_prefix(digits, _FRENCH_DIAL_PREFIXES):
            return True
    return False


def _has_foreign_phone(text: str) -> bool:
    for match in _INTL_PHONE_RE.finditer(text):
        digits = re.sub(r"\D", "", match.group(1))
        if digits and not _starts_with_prefix(digits, _FRENCH_DIAL_PREFIXES):
            return True
    return False


def _starts_with_prefix(digits: str, prefixes: tuple[str, ...]) -> bool:
    return any(digits.startswith(prefix) for prefix in sorted(prefixes, key=len, reverse=True))


def _has_foreign_flag(text: str) -> bool:
    return any(flag in text for flag in _FOREIGN_FLAGS)


def _has_listed_phrase(normalized: str, phrases: tuple[str, ...], restaurant_name: str) -> bool:
    name_normalized = normalize_text(restaurant_name)
    name_compact = compact_text(restaurant_name)
    for phrase in phrases:
        if _phrase_belongs_to_name(phrase, name_normalized, name_compact):
            continue
        for match in re.finditer(rf"\b{re.escape(phrase)}\b", normalized):
            prefix = normalized[: match.start()]
            if _CUISINE_ORIGIN_RE.search(prefix):
                continue
            return True
    return False


def _phrase_belongs_to_name(phrase: str, name_normalized: str, name_compact: str) -> bool:
    if not name_normalized:
        return False
    if re.search(rf"\b{re.escape(phrase)}\b", name_normalized):
        return True
    compact_phrase = compact_text(phrase)
    return bool(compact_phrase) and len(compact_phrase) >= 4 and compact_phrase in name_compact
