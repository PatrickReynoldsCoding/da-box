from pathlib import Path

import pytest

from dabox.uploads import UploadRejected, film_destination, music_destination, safe_path_component

MEDIA = Path("/srv/media")


@pytest.mark.parametrize(
    ("name", "expected"),
    [("Frozen", "Frozen"), ("a/b\\c", "abc"), ("../../etc", "etc"), ('What?: "Yes"', "What Yes")],
)
def test_safe_path_component(name: str, expected: str) -> None:
    assert safe_path_component(name) == expected


@pytest.mark.parametrize("name", ["", "...", "///"])
def test_safe_path_component_rejects_empty(name: str) -> None:
    with pytest.raises(UploadRejected):
        safe_path_component(name)


def test_film_destination() -> None:
    assert film_destination(MEDIA, "Frozen", 2013, "frozen.MKV") == MEDIA / "Films" / "Frozen (2013)" / "frozen.MKV"
    assert film_destination(MEDIA, "Home", None, "/tmp/x/home.mp4") == MEDIA / "Films" / "Home" / "home.mp4"


def test_film_destination_rejects_non_video() -> None:
    with pytest.raises(UploadRejected):
        film_destination(MEDIA, "Frozen", 2013, "frozen.sh")


def test_music_destination_falls_back_to_unknown() -> None:
    assert music_destination(MEDIA, "", "", "song.mp3") == MEDIA / "Music" / "Unknown artist" / "Unknown album" / "song.mp3"
