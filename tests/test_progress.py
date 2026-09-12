"""Tests de la sauvegarde de progression (reprise après interruption)."""

from __future__ import annotations

from pathlib import Path

from restaurant_finder.progress import SearchProgress, compute_run_id, progress_dir_for


def test_compute_run_id_is_stable_regardless_of_order() -> None:
    assert compute_run_id(["node/2", "node/1"]) == compute_run_id(["node/1", "node/2"])


def test_compute_run_id_differs_when_osm_ids_differ() -> None:
    assert compute_run_id(["node/1"]) != compute_run_id(["node/1", "node/2"])


def test_compute_run_id_differs_when_extra_criteria_differ() -> None:
    assert compute_run_id(["node/1"], 1000) != compute_run_id(["node/1"], 500)


def test_progress_dir_for_appends_progress_subdir(tmp_path: Path) -> None:
    assert progress_dir_for(tmp_path) == tmp_path / "progress"


def test_search_progress_load_returns_empty_dict_when_no_file(tmp_path: Path) -> None:
    progress = SearchProgress(tmp_path, "abc123")
    assert progress.load() == {}


def test_search_progress_mark_done_persists_and_reloads(tmp_path: Path) -> None:
    progress = SearchProgress(tmp_path, "abc123")
    progress.mark_done("node/1", {"instagram_url": "https://www.instagram.com/x/"})
    progress.mark_done("node/2", {"instagram_url": None})

    # Nouvelle instance (simule un redémarrage du programme) : doit relire le disque.
    reloaded = SearchProgress(tmp_path, "abc123")
    data = reloaded.load()

    assert data["node/1"]["instagram_url"] == "https://www.instagram.com/x/"
    assert data["node/2"]["instagram_url"] is None


def test_search_progress_clear_removes_file(tmp_path: Path) -> None:
    progress = SearchProgress(tmp_path, "abc123")
    progress.mark_done("node/1", {"instagram_url": None})
    assert progress.path.exists()

    progress.clear()

    assert not progress.path.exists()
    assert SearchProgress(tmp_path, "abc123").load() == {}


def test_search_progress_ignores_corrupted_file(tmp_path: Path) -> None:
    progress_dir = tmp_path
    progress_dir.mkdir(parents=True, exist_ok=True)
    (progress_dir / "abc123.json").write_text("{ceci n'est pas du json", encoding="utf-8")

    progress = SearchProgress(progress_dir, "abc123")

    assert progress.load() == {}


def test_search_progress_different_run_ids_are_isolated(tmp_path: Path) -> None:
    progress_a = SearchProgress(tmp_path, "run-a")
    progress_a.mark_done("node/1", {"instagram_url": None})

    progress_b = SearchProgress(tmp_path, "run-b")
    assert progress_b.load() == {}
