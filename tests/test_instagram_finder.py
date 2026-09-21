"""Tests du service de recherche du profil Instagram."""

from __future__ import annotations

import requests
import responses

from restaurant_finder.config import Settings
from restaurant_finder.domain.models import InstagramConfidence, Restaurant
from restaurant_finder.enrichment.instagram_finder import InstagramFinder
from restaurant_finder.enrichment.instagram_profile import InstagramProfile
from restaurant_finder.enrichment.search_providers.base import SearchProvider, SearchResult


class _StubSearchProvider(SearchProvider):
    def __init__(self, results: list[SearchResult]) -> None:
        self._results = results
        self.call_count = 0
        self.queries: list[str] = []

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        self.call_count += 1
        self.queries.append(query)
        return self._results[:max_results]


class _CascadingSearchProvider(SearchProvider):
    """Renvoie des résultats différents selon le rang de la requête (pour tester la cascade)."""

    def __init__(self, results_by_call: list[list[SearchResult]]) -> None:
        self._results_by_call = results_by_call
        self.call_count = 0
        self.queries: list[str] = []

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        self.queries.append(query)
        index = self.call_count
        self.call_count += 1
        if index >= len(self._results_by_call):
            return []
        return self._results_by_call[index][:max_results]


class _StubProfileClient:
    """Simule `InstagramProfileClient` sans appel réseau."""

    def __init__(self, profiles: dict[str, InstagramProfile | None]) -> None:
        self._profiles = profiles
        self.fetch_count = 0

    def get_profile(self, handle_or_url: str) -> InstagramProfile | None:
        self.fetch_count += 1
        handle = handle_or_url.rstrip("/").split("/")[-1]
        return self._profiles.get(handle)


def _profile(
    handle: str,
    full_name: str = "",
    biography: str = "",
    followers: int = 100,
) -> InstagramProfile:
    return InstagramProfile(
        username=handle,
        full_name=full_name,
        biography=biography,
        follower_count=followers,
        is_private=False,
    )


def _settings(**overrides: object) -> Settings:
    return Settings(instagram_search_delay_seconds=0, **overrides)  # type: ignore[arg-type]


def test_find_returns_best_matching_instagram_profile(sample_restaurant: Restaurant) -> None:
    results = [
        SearchResult(title="Pharmacie du Centre", url="https://pharmacieducentre.fr"),
        SearchResult(
            title="Le Petit Bistrot (@lepetitbistrot_officiel) • Instagram",
            url="https://www.instagram.com/lepetitbistrot_officiel/",
        ),
    ]
    finder = InstagramFinder(_StubSearchProvider(results), _settings())

    match = finder.find(sample_restaurant)
    assert match is not None
    assert match.url == "https://www.instagram.com/lepetitbistrot_officiel/"
    assert match.confidence == InstagramConfidence.ELEVE  # nom fort dans le handle


def test_find_returns_none_when_no_candidate_passes_threshold(
    sample_restaurant: Restaurant,
) -> None:
    results = [
        SearchResult(
            title="Pharmacie du Centre", url="https://www.instagram.com/pharmacieducentre/"
        )
    ]
    finder = InstagramFinder(_StubSearchProvider(results), _settings(instagram_match_threshold=90))

    assert finder.find(sample_restaurant) is None


def test_find_ignores_non_profile_instagram_urls(sample_restaurant: Restaurant) -> None:
    results = [
        SearchResult(title="Publication", url="https://www.instagram.com/p/ABC123/"),
        SearchResult(title="Popular", url="https://www.instagram.com/popular/le-petit-bistrot/"),
        SearchResult(title="Le Petit Bistrot", url="https://www.instagram.com/lepetitbistrot/"),
    ]
    finder = InstagramFinder(_StubSearchProvider(results), _settings())

    match = finder.find(sample_restaurant)
    assert match is not None
    assert match.url == "https://www.instagram.com/lepetitbistrot/"


def test_find_uses_osm_instagram_without_searching(sample_restaurant: Restaurant) -> None:
    sample_restaurant.instagram_url = "https://www.instagram.com/lepetitbistrot/"
    provider = _StubSearchProvider([])
    finder = InstagramFinder(provider, _settings())

    match = finder.find(sample_restaurant)
    assert match is not None
    assert match.url == "https://www.instagram.com/lepetitbistrot/"
    assert match.confidence == InstagramConfidence.ELEVE
    assert provider.call_count == 0


def test_find_osm_instagram_forces_eleve_even_when_handle_does_not_match_name() -> None:
    """Tag OSM contact:instagram → Élevé forcé, indépendamment du nom du restaurant."""

    restaurant = Restaurant(
        osm_id="node/42",
        name="La Table du Chef",
        category="Restaurant",
        city="Paris",
        instagram_url="https://www.instagram.com/compte_sans_rapport/",
    )
    provider = _StubSearchProvider(
        [
            SearchResult(
                title="La Table du Chef",
                url="https://www.instagram.com/latableduchef/",
            )
        ]
    )
    finder = InstagramFinder(provider, _settings())

    match = finder.find(restaurant)

    assert match is not None
    assert match.url == "https://www.instagram.com/compte_sans_rapport/"
    assert match.confidence == InstagramConfidence.ELEVE
    assert provider.call_count == 0


def test_find_osm_instagram_foreign_bio_is_faible() -> None:
    """Tag OSM fiable, mais bio clairement espagnole → Faible pour revue."""

    restaurant = Restaurant(
        osm_id="node/42",
        name="Le Petit Bistrot",
        category="Restaurant",
        city="Lyon",
        instagram_url="https://www.instagram.com/lepetitbistrot/",
    )
    profiles = {
        "lepetitbistrot": _profile(
            "lepetitbistrot",
            full_name="Le Petit Bistrot",
            biography="Barcelona, España 🇪🇸 +34 932 000 000",
        )
    }
    provider = _StubSearchProvider([])
    finder = InstagramFinder(
        provider, _settings(), profile_client=_StubProfileClient(profiles)
    )

    match = finder.find(restaurant)

    assert match is not None
    assert match.url == "https://www.instagram.com/lepetitbistrot/"
    assert match.confidence == InstagramConfidence.FAIBLE
    assert provider.call_count == 0


def test_find_scrapes_website_before_ddg(sample_restaurant: Restaurant) -> None:
    sample_restaurant.website = "https://lepetitbistrot.fr/"
    provider = _StubSearchProvider(
        [
            SearchResult(
                title="Le Petit Bistrot",
                url="https://www.instagram.com/autre_compte/",
            )
        ]
    )

    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            "https://lepetitbistrot.fr/",
            body=(
                '<html><body><a href="https://www.instagram.com/lepetitbistrot_site/">'
                "Suivez-nous</a></body></html>"
            ),
            status=200,
        )
        finder = InstagramFinder(
            provider,
            _settings(),
            http_session=requests.Session(),
        )

        match = finder.find(sample_restaurant)

    assert match is not None
    assert match.url == "https://www.instagram.com/lepetitbistrot_site/"
    assert match.confidence == InstagramConfidence.ELEVE
    assert provider.call_count == 0


def test_find_skips_website_when_osm_instagram_present(sample_restaurant: Restaurant) -> None:
    sample_restaurant.instagram_url = "https://www.instagram.com/osm_handle/"
    sample_restaurant.website = "https://lepetitbistrot.fr/"
    provider = _StubSearchProvider([])

    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.GET,
            "https://lepetitbistrot.fr/",
            body=(
                '<html><body><a href="https://www.instagram.com/site_handle/">'
                "Instagram</a></body></html>"
            ),
            status=200,
        )
        finder = InstagramFinder(
            provider,
            _settings(),
            http_session=requests.Session(),
        )

        match = finder.find(sample_restaurant)

    assert match is not None
    assert match.url == "https://www.instagram.com/osm_handle/"
    assert len(rsps.calls) == 0
    assert provider.call_count == 0


def test_find_falls_back_to_ddg_when_website_has_no_instagram(
    sample_restaurant: Restaurant,
) -> None:
    sample_restaurant.website = "https://lepetitbistrot.fr/"
    provider = _StubSearchProvider(
        [
            SearchResult(
                title="Le Petit Bistrot",
                url="https://www.instagram.com/lepetitbistrot/",
            )
        ]
    )

    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.GET,
            "https://lepetitbistrot.fr/",
            body="<html><body>Pas de réseaux sociaux</body></html>",
            status=200,
        )
        finder = InstagramFinder(
            provider,
            _settings(),
            http_session=requests.Session(),
        )

        match = finder.find(sample_restaurant)

    assert match is not None
    assert match.url == "https://www.instagram.com/lepetitbistrot/"
    assert provider.call_count == 1


def test_find_falls_back_to_ddg_when_website_is_unreachable(
    sample_restaurant: Restaurant,
) -> None:
    sample_restaurant.website = "https://site-down.fr/"
    provider = _StubSearchProvider(
        [
            SearchResult(
                title="Le Petit Bistrot",
                url="https://www.instagram.com/lepetitbistrot/",
            )
        ]
    )

    with responses.RequestsMock() as rsps:
        rsps.add(responses.GET, "https://site-down.fr/", status=503)
        finder = InstagramFinder(
            provider,
            _settings(),
            http_session=requests.Session(),
        )

        match = finder.find(sample_restaurant)

    assert match is not None
    assert match.url == "https://www.instagram.com/lepetitbistrot/"
    assert provider.call_count == 1


def test_find_prefers_city_in_handle(sample_restaurant: Restaurant) -> None:
    results = [
        SearchResult(
            title="Foodie",
            url="https://www.instagram.com/randomfoodie/",
        ),
        SearchResult(
            title="Le Petit Bistrot Lyon",
            url="https://www.instagram.com/lepetitbistrot_lyon/",
        ),
    ]
    finder = InstagramFinder(_StubSearchProvider(results), _settings(instagram_match_threshold=40))

    match = finder.find(sample_restaurant)
    assert match is not None
    assert match.url == "https://www.instagram.com/lepetitbistrot_lyon/"


def test_find_returns_none_when_no_instagram_url(sample_restaurant: Restaurant) -> None:
    results = [SearchResult(title="Le Petit Bistrot", url="https://www.facebook.com/lepetitbistrot/")]
    provider = _StubSearchProvider(results)
    finder = InstagramFinder(provider, _settings())

    assert finder.find(sample_restaurant) is None
    # Cascade : 4 formulations tentées faute de handle Instagram exploitable.
    assert provider.call_count == 4


def test_build_queries_cascade_order(sample_restaurant: Restaurant) -> None:
    queries = InstagramFinder._build_queries(sample_restaurant)
    assert queries == [
        'site:instagram.com "Le Petit Bistrot" "Lyon"',
        '"Le Petit Bistrot" "Lyon" instagram',
        '"Le Petit Bistrot" instagram site:instagram.com',
        "Le Petit Bistrot Lyon instagram",
    ]


def test_cascade_stops_when_first_query_yields_candidates(
    sample_restaurant: Restaurant,
) -> None:
    provider = _CascadingSearchProvider(
        [
            [
                SearchResult(
                    title="Le Petit Bistrot",
                    url="https://www.instagram.com/lepetitbistrot/",
                )
            ],
            [
                SearchResult(
                    title="Autre",
                    url="https://www.instagram.com/autre_compte/",
                )
            ],
        ]
    )
    finder = InstagramFinder(provider, _settings())

    match = finder.find(sample_restaurant)

    assert match is not None
    assert match.url == "https://www.instagram.com/lepetitbistrot/"
    assert provider.call_count == 1
    assert provider.queries[0].startswith("site:instagram.com")


def test_cascade_tries_next_query_when_first_has_no_instagram(
    sample_restaurant: Restaurant,
) -> None:
    provider = _CascadingSearchProvider(
        [
            [SearchResult(title="Annuaire", url="https://tripadvisor.fr/le-petit-bistrot")],
            [
                SearchResult(
                    title="Le Petit Bistrot Instagram",
                    url="https://www.instagram.com/lepetitbistrot/",
                )
            ],
        ]
    )
    finder = InstagramFinder(provider, _settings())

    match = finder.find(sample_restaurant)

    assert match is not None
    assert match.url == "https://www.instagram.com/lepetitbistrot/"
    assert provider.call_count == 2
    assert '"Le Petit Bistrot" "Lyon" instagram' in provider.queries[1]


def test_extracts_instagram_handle_from_snippet_when_url_is_not_instagram(
    sample_restaurant: Restaurant,
) -> None:
    results = [
        SearchResult(
            title="Le Petit Bistrot — restaurant à Lyon",
            url="https://www.lepetitbistrot-lyon.fr/",
            snippet=(
                "Réservez et suivez-nous sur Instagram : "
                "https://www.instagram.com/lepetitbistrot_off/"
            ),
        )
    ]
    finder = InstagramFinder(_StubSearchProvider(results), _settings())

    match = finder.find(sample_restaurant)

    assert match is not None
    assert match.url == "https://www.instagram.com/lepetitbistrot_off/"


def test_find_uses_cache_and_avoids_second_search(sample_restaurant: Restaurant, tmp_path) -> None:
    from restaurant_finder.cache import FileCache

    provider = _StubSearchProvider(
        [
            SearchResult(
                title="Le Petit Bistrot",
                url="https://www.instagram.com/lepetitbistrot/",
            )
        ]
    )
    cache = FileCache(tmp_path, ttl_seconds=3600)
    finder = InstagramFinder(provider, _settings(), cache=cache)

    first = finder.find(sample_restaurant)
    second = finder.find(sample_restaurant)

    assert first is not None and second is not None
    assert first.url == second.url
    assert provider.call_count == 1


def test_find_marks_false_positive_as_faible_for_manual_review(
    sample_restaurant: Restaurant,
) -> None:
    """Un extrait flatteur mais un vrai profil sans rapport : confiance Faible."""

    results = [
        SearchResult(
            title="Le Petit Bistrot - avis, horaires, menu | annuaire restaurants",
            url="https://www.instagram.com/xyz_random_account/",
            snippet="Le Petit Bistrot Lyon restaurant",
        )
    ]
    profiles = {
        "xyz_random_account": _profile(
            "xyz_random_account", full_name="Voyages & Photographie", biography="Blog voyage"
        )
    }
    finder = InstagramFinder(
        _StubSearchProvider(results), _settings(), profile_client=_StubProfileClient(profiles)
    )

    match = finder.find(sample_restaurant)
    assert match is not None
    assert match.url == "https://www.instagram.com/xyz_random_account/"
    assert match.confidence == InstagramConfidence.FAIBLE


def test_find_accepts_candidate_confirmed_by_profile_bio(sample_restaurant: Restaurant) -> None:
    results = [
        SearchResult(
            title="Bistrot",
            url="https://www.instagram.com/lepetitbistrot_off/",
            snippet="",
        )
    ]
    profiles = {
        "lepetitbistrot_off": _profile(
            "lepetitbistrot_off",
            full_name="LPB",
            biography="Le Petit Bistrot, cuisine traditionnelle à Lyon",
            followers=300,
        )
    }
    finder = InstagramFinder(
        _StubSearchProvider(results), _settings(), profile_client=_StubProfileClient(profiles)
    )

    match = finder.find(sample_restaurant)
    assert match is not None
    assert match.url == "https://www.instagram.com/lepetitbistrot_off/"
    assert match.confidence == InstagramConfidence.ELEVE


def test_find_downgrades_matching_name_when_bio_is_in_spain(
    sample_restaurant: Restaurant,
) -> None:
    """Handle identique au nom, mais établissement espagnol → Faible."""

    results = [
        SearchResult(
            title="Le Petit Bistrot",
            url="https://www.instagram.com/lepetitbistrot/",
        )
    ]
    profiles = {
        "lepetitbistrot": _profile(
            "lepetitbistrot",
            full_name="Le Petit Bistrot",
            biography="Restaurante en Barcelona +34 932 000 000",
        )
    }
    finder = InstagramFinder(
        _StubSearchProvider(results),
        _settings(),
        profile_client=_StubProfileClient(profiles),
    )

    match = finder.find(sample_restaurant)
    assert match is not None
    assert match.url == "https://www.instagram.com/lepetitbistrot/"
    assert match.confidence == InstagramConfidence.FAIBLE


def test_find_only_checks_a_bounded_number_of_profiles(sample_restaurant: Restaurant) -> None:
    results = [
        SearchResult(title="Le Petit Bistrot", url=f"https://www.instagram.com/candidat{i}/")
        for i in range(6)
    ]
    profile_client = _StubProfileClient({})  # aucun profil trouvable
    finder = InstagramFinder(
        _StubSearchProvider(results),
        _settings(instagram_max_profile_checks=2),
        profile_client=profile_client,
    )

    finder.find(sample_restaurant)

    # `instagram_max_profile_checks=2` borne le total de vérifications réseau
    # pour ce restaurant, même avec 6 candidats trouvés.
    assert profile_client.fetch_count <= 2


def test_find_marks_same_name_different_city_as_faible() -> None:
    """Enseigne régionale au nom proche mais autre ville → Faible (revue manuelle)."""

    restaurant = Restaurant(
        osm_id="node/99", name="Le Castello", category="Restaurant", city="Nice"
    )
    results = [
        SearchResult(title="Le Castello", url="https://www.instagram.com/ilcastello_brest/")
    ]
    # Ni le nom complet, ni la bio ne confirment la ville du restaurant (Nice).
    # Score profil insuffisant → candidat conservé en Faible pour revue manuelle.
    profiles = {
        "ilcastello_brest": _profile(
            "ilcastello_brest",
            full_name="Il Castello Brest",
            biography="Restaurant italien à Brest",
            followers=500,
        )
    }
    finder = InstagramFinder(
        _StubSearchProvider(results), _settings(), profile_client=_StubProfileClient(profiles)
    )

    match = finder.find(restaurant)
    assert match is not None
    assert match.confidence == InstagramConfidence.FAIBLE


def test_find_falls_back_to_text_score_when_instagram_is_unreachable(
    sample_restaurant: Restaurant,
) -> None:
    results = [
        SearchResult(
            title="Le Petit Bistrot Officiel",
            url="https://www.instagram.com/lepetitbistrot/",
        )
    ]
    profile_client = _StubProfileClient({})  # get_profile renvoie toujours None
    finder = InstagramFinder(
        _StubSearchProvider(results), _settings(), profile_client=profile_client
    )

    match = finder.find(sample_restaurant)
    assert match is not None
    assert match.url == "https://www.instagram.com/lepetitbistrot/"
    assert match.confidence == InstagramConfidence.ELEVE
