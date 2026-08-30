"""Tests de normalisation des handles / URLs Instagram."""

from restaurant_finder.enrichment.instagram_normalize import (
    extract_handle,
    extract_handles_from_text,
    to_profile_url,
)


def test_extract_handle_from_url() -> None:
    assert extract_handle("https://www.instagram.com/lesafari_nice/") == "lesafari_nice"


def test_extract_handle_from_at_prefix() -> None:
    assert extract_handle("@lesafari_nice") == "lesafari_nice"


def test_extract_handle_ignores_posts_and_popular() -> None:
    assert extract_handle("https://www.instagram.com/p/ABC123/") is None
    assert extract_handle("https://www.instagram.com/popular/le-safari-nice/") is None


def test_extract_handles_from_text_in_snippet() -> None:
    text = (
        "Le Petit Bistrot Lyon — suivez-nous sur "
        "https://www.instagram.com/lepetitbistrot_off/ et Facebook."
    )
    assert extract_handles_from_text(text) == ["lepetitbistrot_off"]


def test_extract_handles_from_text_skips_reserved_paths() -> None:
    text = "Voir https://instagram.com/p/ABC123/ et https://instagram.com/lepetitbistrot/"
    assert extract_handles_from_text(text) == ["lepetitbistrot"]


def test_to_profile_url_from_raw_handle() -> None:
    assert to_profile_url("lesafari_nice") == "https://www.instagram.com/lesafari_nice/"
