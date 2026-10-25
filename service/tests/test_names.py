"""Name rules, with real names from the Toshiba drive on the Mint laptop (DESIGN_CORRECTIONS_2.md)."""

import pytest

from dabox.names import (
    clean_name,
    episode_marker,
    natural_key,
    split_artist_title,
    split_year,
    strip_track_number,
    without_common_start,
)


@pytest.mark.parametrize(("raw", "clean"), [
    ("Fargo (2014) Season 5 S05 (1080p AMZN WEB-DL x265 HEVC 10bit EAC3 5.1 Silence)", "Fargo (2014) Season 5"),
    ("Fargo (2014) - S05E03 - The Paradox of Intermediate Transactions (1080p AMZN WEB-DL x265 Silence)",
     "Fargo (2014) - S05E03 - The Paradox of Intermediate Transactions"),
    ("Guitar Heroes at the BBC, 2010, XviD (1-6)", "Guitar Heroes at the BBC, 2010"),
    ("Even More Guitar Heroes at the BBC (10th July 2009) [PDTV (XviD)] WatchTheBox", "Even More Guitar Heroes at the BBC (10th July 2009)"),
    ("Guitar Heroes at the BBC (17th October 2008) [TVRip (XviD)]", "Guitar Heroes at the BBC (17th October 2008)"),
    ("Guitar Heroes at the BBC - Part 4 (31 Dec 2009) [PDTV (XviD)] WTB", "Guitar Heroes at the BBC - Part 4 (31 Dec 2009)"),
    ("BBC_The_Genius_of_Design", "BBC The Genius of Design"),
    ("BBC The Genius Of Design 1 of 5 Ghosts In The Machine 2010", "BBC The Genius Of Design 1 of 5 Ghosts In The Machine 2010"),
    ("Chris Thile Mandolin - Homespun", "Chris Thile Mandolin - Homespun"),
    ("Some.Film.2014.1080p.BluRay.x264-GROUP", "Some Film (2014)"),
    ("Blade Runner 2049", "Blade Runner 2049"),
    ("Frozen (2013)", "Frozen (2013)"),
    # A title word that looks like a tag in lower case stays.
    ("The Nf Story", "The Nf Story"),
    # Nothing but tags: keep the name rather than nothing.
    ("1080p", "1080p"),
])
def test_clean_name(raw: str, clean: str) -> None:
    assert clean_name(raw) == clean


@pytest.mark.parametrize(("name", "expected"), [
    ("Frozen (2013)", ("Frozen", 2013)),
    ("Some Film (2014)", ("Some Film", 2014)),
    ("Some Film [1999]", ("Some Film", 1999)),
    ("Home Movie", ("Home Movie", None)),
    ("2012", ("2012", None)),
    ("Blade Runner 2049", ("Blade Runner 2049", None)),
    ("BBC The Genius Of Design 1 of 5 Ghosts In The Machine 2010", ("BBC The Genius Of Design 1 of 5 Ghosts In The Machine 2010", None)),
])
def test_split_year(name: str, expected: tuple[str, int | None]) -> None:
    assert split_year(name) == expected


def test_natural_key_sorts_numbers_as_numbers() -> None:
    names = ["Part 10", "part 2", "Part 1", "Season 2/03", "Season 10/01", "Season 2/1"]
    assert sorted(names, key=natural_key) == ["Part 1", "part 2", "Part 10", "Season 2/1", "Season 2/03", "Season 10/01"]


@pytest.mark.parametrize(("text", "marker"), [
    ("Fargo (2014) - S05E03 - The Paradox", (5, 3)),
    ("bluey s1e2", (1, 2)),
    ("Show.S01.E02.mkv", (1, 2)),
    ("Show 1x02", (1, 2)),
    ("BBC The Genius Of Design 1 of 5", None),
    ("Mortage calculator ver 2", None),
    ("1920x1080 test", None),
])
def test_episode_marker(text: str, marker: tuple[int, int] | None) -> None:
    assert episode_marker(text) == marker


@pytest.mark.parametrize(("stem", "expected"), [
    ("07 - Hello Goodbye", ("Hello Goodbye", 7)),
    ("10 Hiphopopotamus vs. Rhymenocerous", ("Hiphopopotamus vs. Rhymenocerous", 10)),
    ("(16) Nick Lowe - Raining Raining 1", ("Nick Lowe - Raining Raining 1", 16)),
    ("01. Opening", ("Opening", 1)),
    # A date is not a track number, and an inner extension goes.
    ("20140606 131826.m4a", ("20140606 131826", None)),
    ("Yesterday", ("Yesterday", None)),
    ("99", ("99", None)),
])
def test_strip_track_number(stem: str, expected: tuple[str, int | None]) -> None:
    assert strip_track_number(stem) == expected


@pytest.mark.parametrize(("stem", "expected"), [
    ("(16) Nick Lowe - Raining Raining 1", ("Nick Lowe", "Raining Raining 1")),
    ("(19) Nick Lowe - Wish You Were Here", ("Nick Lowe", "Wish You Were Here")),
    ("07 - Hello Goodbye", (None, "Hello Goodbye")),
    ("Hello Goodbye", (None, "Hello Goodbye")),
    ("2010 - 2011 - Song", (None, "2010 - 2011 - Song")),
])
def test_split_artist_title(stem: str, expected: tuple[str | None, str]) -> None:
    assert split_artist_title(stem) == expected


def test_without_common_start() -> None:
    names = [
        "BBC The Genius Of Design 1 of 5 Ghosts In The Machine 2010",
        "BBC The Genius of Design 4 of 5 Better Living Through Chemistry 2010",
    ]
    assert without_common_start(names) == ["1 of 5 Ghosts In The Machine 2010", "4 of 5 Better Living Through Chemistry 2010"]
    # Keeps the names when nothing is shared, when one would become empty, or with one name.
    assert without_common_start(["Alpha one", "Beta two"]) == ["Alpha one", "Beta two"]
    assert without_common_start(["Show", "Show Part 2"]) == ["Show", "Show Part 2"]
    assert without_common_start(["Only one"]) == ["Only one"]
