"""Tests du service de recherche du profil Instagram."""

from __future__ import annotations

from restaurant_finder.config import Settings
from restaurant_finder.domain.models import Restaurant
from restaurant_finder.enrichment.instagram_finder import InstagramFinder
from restaurant_finder.enrichment.instagram_profile import InstagramProfile
from restaurant_finder.enrichment.search_providers.base import SearchProvider, SearchResult


class _StubSearchProvider(SearchProvider):
    def __init__(self, results: list[SearchResult]) -> None:
        self._results = results
        self.call_count = 0

    def search(self, query: str, max_results: int) -> list[SearchResult]:
        self.call_count += 1
        return self._results[:max_results]


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
    username: str, full_name: str = "", biography: str = "", followers: int = 100
) -> InstagramProfile:
    return InstagramProfile(
        username=username,
        full_name=full_name,
        biography=biography,
        follower_count=followers,
        is_private=False,
    )


class _FakeCache:
    def __init__(self) -> None:
        self.store: dict[str, object] = {}

    def get(self, key: str) -> object | None:
        return self.store.get(key)

    def set(self, key: str, value: object) -> None:
        self.store[key] = value


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

    assert finder.find(sample_restaurant) == "https://www.instagram.com/lepetitbistrot_officiel/"


def test_find_returns_none_when_no_result_meets_threshold(sample_restaurant: Restaurant) -> None:
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

    assert finder.find(sample_restaurant) == "https://www.instagram.com/lepetitbistrot/"


def test_find_uses_osm_instagram_without_searching(sample_restaurant: Restaurant) -> None:
    sample_restaurant.instagram_url = "https://www.instagram.com/osm_handle/"
    provider = _StubSearchProvider([])
    finder = InstagramFinder(provider, _settings())

    assert finder.find(sample_restaurant) == "https://www.instagram.com/osm_handle/"
    assert provider.call_count == 0


def test_find_boosts_handle_containing_city_name(sample_restaurant: Restaurant) -> None:
    results = [
        SearchResult(
            title="Autre compte",
            url="https://www.instagram.com/randomfoodie/",
        ),
        SearchResult(
            title="Le Petit Bistrot Nice",
            url="https://www.instagram.com/lepetitbistrot_lyon/",
        ),
    ]
    finder = InstagramFinder(_StubSearchProvider(results), _settings(instagram_match_threshold=40))

    assert finder.find(sample_restaurant) == "https://www.instagram.com/lepetitbistrot_lyon/"


def test_find_ignores_urls_from_other_domains(sample_restaurant: Restaurant) -> None:
    results = [SearchResult(title="Le Petit Bistrot", url="https://www.facebook.com/lepetitbistrot/")]
    finder = InstagramFinder(_StubSearchProvider(results), _settings())

    assert finder.find(sample_restaurant) is None


def test_find_uses_cache_and_avoids_second_search(sample_restaurant: Restaurant) -> None:
    provider = _StubSearchProvider([])
    cache = _FakeCache()
    finder = InstagramFinder(provider, _settings(), cache=cache)

    first = finder.find(sample_restaurant)
    second = finder.find(sample_restaurant)

    assert first is None
    assert second is None
    # 2 formulations de requête au 1er passage, puis lecture cache.
    assert provider.call_count == 2


def test_find_rejects_false_positive_using_real_profile_verification(
    sample_restaurant: Restaurant,
) -> None:
    """Un extrait de recherche flatteur mais un vrai profil sans rapport : rejeté."""

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

    assert finder.find(sample_restaurant) is None


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

    assert finder.find(sample_restaurant) == "https://www.instagram.com/lepetitbistrot_off/"


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


def test_find_rejects_same_name_different_city_chain_location() -> None:
    """Piège classique : une enseigne régionale au nom quasi identique mais
    située dans une autre ville (ex: "Le Castello" à Nice vs un compte
    "@ilcastello_brest" sans lien réel avec le restaurant recherché)."""

    restaurant = Restaurant(
        osm_id="node/99", name="Le Castello", category="Restaurant", city="Nice"
    )
    results = [
        SearchResult(title="Le Castello", url="https://www.instagram.com/ilcastello_brest/")
    ]
    profiles = {
        # Ni le nom complet, ni la bio ne confirment la ville du restaurant (Nice).
        "ilcastello_brest": _profile("ilcastello_brest", full_name="", biography="", followers=500)
    }
    finder = InstagramFinder(
        _StubSearchProvider(results), _settings(), profile_client=_StubProfileClient(profiles)
    )

    assert finder.find(restaurant) is None


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

    assert finder.find(sample_restaurant) == "https://www.instagram.com/lepetitbistrot/"
