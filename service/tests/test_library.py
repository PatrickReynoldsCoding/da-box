import shutil
import subprocess
from pathlib import Path

import pytest

from dabox.library import (
    item_id,
    parse_film_name,
    parse_track_number,
    scan_films,
    scan_music,
    title_from_file_name,
)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Frozen (2013)", ("Frozen", 2013)),
        ("Toy Story 2 (1999)", ("Toy Story 2", 1999)),
        ("Home Movie", ("Home Movie", None)),
        ("  Spaced  ", ("Spaced", None)),
    ],
)
def test_parse_film_name(name: str, expected: tuple[str, int | None]) -> None:
    assert parse_film_name(name) == expected


@pytest.mark.parametrize(("raw", "expected"), [("3/12", 3), ("07", 7), ("", None), (None, None), ("A1", None)])
def test_parse_track_number(raw: str | None, expected: int | None) -> None:
    assert parse_track_number(raw) == expected


def test_title_from_file_name_drops_track_number() -> None:
    assert title_from_file_name(Path("01 - Opening.mp3")) == "Opening"
    assert title_from_file_name(Path("Intro.mp3")) == "Intro"


def test_item_id_is_stable_and_kind_specific() -> None:
    assert item_id("film", "Films/a.mkv") == item_id("film", "Films/a.mkv")
    assert item_id("film", "Films/a.mkv") != item_id("album", "Films/a.mkv")


def test_scan_films_reads_folders_and_loose_files(media_dir: Path) -> None:
    films = scan_films(media_dir)

    assert [(film.title, film.year) for film in films] == [("Frozen", 2013), ("Home Movie", None)]
    frozen = films[0]
    assert frozen.art_path == media_dir / "Films" / "Frozen (2013)" / "poster.jpg"
    assert films[1].art_path is None


def test_scan_music_groups_tracks_by_folder_and_uses_folder_names(media_dir: Path) -> None:
    albums = scan_music(media_dir)

    assert len(albums) == 1
    album = albums[0]
    assert (album.artist, album.title) == ("The Band", "First Album")
    assert [track.title for track in album.tracks] == ["Opening", "Second Song"]
    assert album.art_path is not None


def test_scan_handles_missing_folders(tmp_path: Path) -> None:
    assert scan_films(tmp_path) == []
    assert scan_music(tmp_path) == []


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg to make a tagged file")
def test_scan_music_prefers_tags(tmp_path: Path) -> None:
    track_path = tmp_path / "Music" / "folder artist" / "folder album" / "x.mp3"
    track_path.parent.mkdir(parents=True)
    subprocess.run(
        [
            "ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-metadata", "title=Tagged Title", "-metadata", "artist=Tag Artist", "-metadata", "album=Tag Album",
            "-metadata", "track=4", str(track_path),
        ],
        check=True,
    )

    album = scan_music(tmp_path)[0]

    assert (album.artist, album.title) == ("Tag Artist", "Tag Album")
    assert (album.tracks[0].title, album.tracks[0].track_number) == ("Tagged Title", 4)
