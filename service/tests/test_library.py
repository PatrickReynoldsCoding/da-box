import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from dabox.library import (
    UNKNOWN_ALBUM,
    UNKNOWN_ARTIST,
    item_id,
    parse_film_name,
    parse_track_number,
    scan_root,
    title_from_file_name,
)
from dabox.models import MediaSource
from dabox.usb import UsbStick
from tests.conftest import write_file


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


def test_scan_handles_a_missing_or_empty_folder(tmp_path: Path) -> None:
    for root in (tmp_path / "missing", tmp_path):
        scan = scan_root(root)
        assert (scan.films, scan.shows, scan.albums, scan.games) == ([], [], [], [])


# ---- The box's own media: the old layout, the same ids (DESIGN_CORRECTIONS_2.md, 2.4) ----

def test_box_layout_keeps_its_items_and_ids(media_dir: Path) -> None:
    scan = scan_root(media_dir)

    assert [(film.title, film.year) for film in scan.films] == [("Frozen", 2013), ("Home Movie", None)]
    frozen, home_movie = scan.films
    assert frozen.id == item_id("film", "Films/Frozen (2013)/Frozen (2013).mkv")
    assert home_movie.id == item_id("film", "Films/Home Movie.mp4")
    assert frozen.art_path == media_dir / "Films" / "Frozen (2013)" / "poster.jpg"
    assert home_movie.art_path is None

    [bluey] = scan.shows
    assert (bluey.id, bluey.title) == (item_id("show", "TV/Bluey"), "Bluey")
    assert bluey.art_path == media_dir / "TV" / "Bluey" / "poster.jpg"
    assert [(episode.season, episode.number, episode.title, episode.section) for episode in bluey.episodes] == [
        (1, 1, "The Pool", "Season 01"), (1, 2, "Hospital", "Season 01"), (2, 3, "Bike", "Season 2"),
    ]
    assert bluey.episodes[0].id == item_id("episode", "TV/Bluey/Season 01/Bluey S01E01 - The Pool.mp4")

    [album] = scan.albums
    assert album.id == item_id("album", "Music/The Band/First Album")
    assert (album.artist, album.title) == ("The Band", "First Album")
    assert [track.title for track in album.tracks] == ["Opening", "Second Song"]
    assert album.art_path is not None
    assert scan.report.other_files == {".txt": 1}


def test_box_tv_folder_with_one_video_is_still_a_group(tmp_path: Path) -> None:
    write_file(tmp_path / "TV" / "Paw Pals" / "Paw Pals S01E01.mp4")
    scan = scan_root(tmp_path)
    assert scan.films == []
    assert [show.id for show in scan.shows] == [item_id("show", "TV/Paw Pals")]


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

    album = scan_root(tmp_path).albums[0]

    assert (album.artist, album.title) == ("Tag Artist", "Tag Album")
    assert (album.tracks[0].title, album.tracks[0].track_number) == ("Tagged Title", 4)


# ---- A real drive with any layout: the Toshiba disk from the Mint laptop ----

TOSHIBA_FILES = [
    "$RECYCLE.BIN/S-1-5-21/$R1234.mp4",
    "System Volume Information/IndexerVolumeGuid",
    "Mortage calculator ver 2.xlsx",
    "Design/brief.pdf",
    "Design/moodboard.jpg",
    "Cloud backups/photos.zip",
    "Music/07 - Hello Goodbye.mp3",
    "Music/10 Hiphopopotamus vs. Rhymenocerous.mp3",
    "Music/(16) Nick Lowe - Raining Raining 1.mp3",
    "Music/(17) Nick Lowe - Homewrecker.mp3",
    "Music/20140606 131826.m4a.mp3",
    "Music/Radio Heartland/To Improv Over/01 First.mp3",
    "Music/Radio Heartland/To Improv Over/02 Second.mp3",
    "Temp/clip.mp4",
    "Video/Chris Thile Mandolin - Homespun.mp4",
    "Video/Mike Marshall Mandolin - Homespun.mp4",
    "Video/BBC_The_Genius_of_Design/BBC The Genius Of Design 1 of 5 Ghosts In The Machine 2010.avi",
    "Video/BBC_The_Genius_of_Design/BBC The Genius Of Design 2 of 5 Designs For Living 2010.avi",
    "Video/BBC_The_Genius_of_Design/._BBC The Genius Of Design 2 of 5 Designs For Living 2010.avi",
    "Video/BBC_The_Genius_of_Design/BBC The Genius Of Design 3 of 5 Blueprints For War 2010.avi",
    "Video/BBC_The_Genius_of_Design/BBC The Genius of Design 4 of 5 Better Living Through Chemistry 2010.avi",
    "Video/BBC_The_Genius_of_Design/BBC The Genius of Design 5 of 5 Objects Of Desire 2010.avi",
    "Video/Guitar Heroes at the BBC, 2010, XviD (1-6)/Guitar Heroes at the BBC (17th October 2008) [TVRip (XviD)].avi",
    "Video/Guitar Heroes at the BBC, 2010, XviD (1-6)/Guitar Heroes at the BBC - Part 4 (31 Dec 2009) [PDTV (XviD)] WTB.avi",
    "Video/Guitar Heroes at the BBC, 2010, XviD (1-6)/Even More Guitar Heroes at the BBC (10th July 2009) [PDTV (XviD)] WatchTheBox.avi",
    "Video/Fargo (2014) Season 5 S05 (1080p AMZN WEB-DL x265 HEVC 10bit EAC3 5.1 Silence)/Fargo (2014) - S05E03 - The Paradox of Intermediate Transactions (1080p AMZN WEB-DL x265 Silence).mkv",
    "Video/Fargo (2014) Season 5 S05 (1080p AMZN WEB-DL x265 HEVC 10bit EAC3 5.1 Silence)/Fargo (2014) - S05E01 - The Tragedy of the Commons (1080p AMZN WEB-DL x265 Silence).mkv",
    "Video/Fargo (2014) Season 5 S05 (1080p AMZN WEB-DL x265 HEVC 10bit EAC3 5.1 Silence)/Fargo (2014) - S05E02 - Trials and Tribulations (1080p AMZN WEB-DL x265 Silence).mkv",
    "Video/Fargo (2014) Season 5 S05 (1080p AMZN WEB-DL x265 HEVC 10bit EAC3 5.1 Silence)/Fargo (2014) - S05E02 - Trials and Tribulations (1080p AMZN WEB-DL x265 Silence).srt",
    "Video/Arrival (2016)/Arrival.2016.1080p.BluRay.x264.mkv",
    "Video/Arrival (2016)/poster.jpg",
]


@pytest.fixture
def toshiba(tmp_path: Path) -> Path:
    root = tmp_path / "Untitled"
    for number, name in enumerate(TOSHIBA_FILES):
        # Different content for each file, so each gets its own fingerprint.
        write_file(root / name, f"file {number}".encode())
    return root


@pytest.fixture
def toshiba_stick(toshiba: Path) -> UsbStick:
    return UsbStick(id="toshiba", label="Untitled", path=toshiba)


def test_drive_single_videos(toshiba: Path, toshiba_stick: UsbStick) -> None:
    films = {film.title: film for film in scan_root(toshiba, toshiba_stick).films}
    # A video alone in a folder is named after the folder; loose videos after their file;
    # a generic folder ("Temp") does not name its video.
    assert sorted(films, key=str.casefold) == ["Arrival", "Chris Thile Mandolin - Homespun", "clip", "Mike Marshall Mandolin - Homespun"]
    assert films["Arrival"].year == 2016
    assert films["Arrival"].art_path == toshiba / "Video" / "Arrival (2016)" / "poster.jpg"
    assert all(film.source is MediaSource.USB and film.id.startswith("u") for film in films.values())


def test_drive_groups(toshiba: Path, toshiba_stick: UsbStick) -> None:
    groups = {group.title: group for group in scan_root(toshiba, toshiba_stick).shows}
    assert sorted(groups) == ["BBC The Genius of Design", "Fargo (2014) Season 5", "Guitar Heroes at the BBC, 2010"]

    design = groups["BBC The Genius of Design"]
    # In order "1 of 5" to "5 of 5", without the macOS "._" file, and without the shared start.
    assert [episode.title for episode in design.episodes] == [
        "1 of 5 Ghosts In The Machine 2010", "2 of 5 Designs For Living 2010", "3 of 5 Blueprints For War 2010",
        "4 of 5 Better Living Through Chemistry 2010", "5 of 5 Objects Of Desire 2010",
    ]
    assert {episode.season for episode in design.episodes} == {0}

    fargo = groups["Fargo (2014) Season 5"]
    assert [(episode.season, episode.number, episode.title) for episode in fargo.episodes] == [
        (5, 1, "The Tragedy of the Commons"), (5, 2, "Trials and Tribulations"), (5, 3, "The Paradox of Intermediate Transactions"),
    ]

    guitar = groups["Guitar Heroes at the BBC, 2010"]
    assert [episode.title for episode in guitar.episodes] == [
        "Even More Guitar Heroes at the BBC (10th July 2009)",
        "Guitar Heroes at the BBC (17th October 2008)",
        "Guitar Heroes at the BBC - Part 4 (31 Dec 2009)",
    ]
    assert all(group.source is MediaSource.USB and group.stick_label == "Untitled" for group in groups.values())


def test_drive_music_like_itunes(toshiba: Path, toshiba_stick: UsbStick) -> None:
    albums = {(album.artist, album.title): album for album in scan_root(toshiba, toshiba_stick).albums}
    assert sorted(albums) == [
        ("Nick Lowe", UNKNOWN_ALBUM), ("Radio Heartland", "To Improv Over"), (UNKNOWN_ARTIST, UNKNOWN_ALBUM),
    ]
    assert [track.title for track in albums[("Nick Lowe", UNKNOWN_ALBUM)].tracks] == ["Raining Raining 1", "Homewrecker"]
    assert [track.title for track in albums[(UNKNOWN_ARTIST, UNKNOWN_ALBUM)].tracks] == [
        "Hello Goodbye", "Hiphopopotamus vs. Rhymenocerous", "20140606 131826",
    ]


def test_drive_report(toshiba: Path, toshiba_stick: UsbStick) -> None:
    report = scan_root(toshiba, toshiba_stick).report
    assert (report.videos, report.groups, report.albums, report.songs, report.games) == (4, 3, 3, 7, 0)
    assert report.skipped_folders == 2
    # The spreadsheet, the PDF and the photo in Design/, and a zip that is not a game. The
    # subtitle and the poster are next to videos, so they are not "other files".
    assert report.other_files == {".xlsx": 1, ".pdf": 1, ".jpg": 1, ".zip": 1}
    assert report.unreadable == []


def test_same_drive_same_ids(toshiba: Path, toshiba_stick: UsbStick, tmp_path: Path) -> None:
    """USB ids come from the files, so the drive keeps its ids at another mount point."""
    moved = tmp_path / "elsewhere"
    shutil.copytree(toshiba, moved)
    first, second = scan_root(toshiba, toshiba_stick), scan_root(moved, UsbStick(id="toshiba", label="Untitled", path=moved))
    for kind in ("films", "shows", "albums"):
        assert sorted(item.id for item in getattr(first, kind)) == sorted(item.id for item in getattr(second, kind))


# ---- Folders and games ----

def test_section_folders_make_one_group(tmp_path: Path) -> None:
    for name in ["Show/Season 1/a S01E01.mp4", "Show/Season 1/a S01E02.mp4", "Show/Season 10/a S10E01.mp4", "Show/Specials/Making of.mp4"]:
        write_file(tmp_path / name, name.encode())
    [show] = scan_root(tmp_path, UsbStick(id="s", label="S", path=tmp_path)).shows
    assert show.title == "Show"
    # Not every video has a marker, so the order is by name, numbers as numbers.
    assert [episode.section for episode in show.episodes] == ["Season 1", "Season 1", "Season 10", "Specials"]


def test_folder_of_folders_is_a_container(tmp_path: Path) -> None:
    for name in ["Kids films/Cars (2006)/cars.mkv", "Kids films/Up (2009)/up.mkv", "Kids films/loose.mp4"]:
        write_file(tmp_path / name, name.encode())
    scan = scan_root(tmp_path, UsbStick(id="s", label="S", path=tmp_path))
    assert sorted((film.title, film.year) for film in scan.films) == [("Cars", 2006), ("Up", 2009), ("loose", None)]
    assert scan.shows == []


def _zip(path: Path, names: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name in names:
            archive.writestr(name, name)


def test_games_anywhere_by_extension_and_folder(tmp_path: Path) -> None:
    write_file(tmp_path / "Games" / "nes" / "Super Game (USA).nes", b"nes")
    write_file(tmp_path / "loose" / "Pocket Game.gba", b"gba")
    _zip(tmp_path / "ROMs" / "Plumber.zip", ["Plumber.sfc"])
    _zip(tmp_path / "backup.zip", ["notes.txt", "photo.jpg"])
    write_file(tmp_path / "Mega Drive" / "Hedgehog.bin", b"md")
    write_file(tmp_path / "random" / "firmware.bin", b"not a game")
    write_file(tmp_path / "PS1" / "Disc Game" / "Disc Game.cue", b'FILE "Disc Game.bin" BINARY')
    write_file(tmp_path / "PS1" / "Disc Game" / "Disc Game.bin", b"disc")
    write_file(tmp_path / "CD rip" / "Album.cue", b'FILE "01.flac" WAVE')

    scan = scan_root(tmp_path, UsbStick(id="s", label="S", path=tmp_path))

    assert sorted((game.title, game.system) for game in scan.games) == [
        ("Disc Game", "psx"), ("Hedgehog", "megadrive"), ("Plumber", "snes"), ("Pocket Game", "gba"), ("Super Game", "nes"),
    ]
    assert scan.report.other_files == {".zip": 1, ".bin": 1, ".cue": 1}


def test_unreadable_folder_is_reported(tmp_path: Path) -> None:
    locked = tmp_path / "locked"
    write_file(locked / "a.mp4")
    write_file(tmp_path / "ok.mp4", b"ok")
    locked.chmod(0)
    try:
        scan = scan_root(tmp_path, UsbStick(id="s", label="S", path=tmp_path))
    finally:
        locked.chmod(0o755)
    assert [film.title for film in scan.films] == ["ok"]
    if scan.report.unreadable:  # root can read the folder anyway
        assert "locked" in scan.report.unreadable[0]
