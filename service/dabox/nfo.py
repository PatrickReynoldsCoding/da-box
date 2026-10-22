"""Reads Kodi-style .nfo files (XML) that people put next to their media."""

import xml.etree.ElementTree as ElementTree
from pathlib import Path

from pydantic import BaseModel


class NfoDetails(BaseModel):
    title: str | None = None
    year: int | None = None
    plot: str | None = None


def _text(root: ElementTree.Element, tag: str) -> str | None:
    element = root.find(tag)
    if element is None or element.text is None:
        return None
    return element.text.strip() or None


def parse_movie_nfo(text: str) -> NfoDetails | None:
    """Returns None for text that is not a <movie> XML document (some .nfo files are only a URL)."""
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError:
        return None
    if root.tag != "movie":
        return None
    year_text = _text(root, "year") or (_text(root, "premiered") or "")[:4]
    return NfoDetails(
        title=_text(root, "title"),
        year=int(year_text) if year_text and year_text.isdigit() else None,
        plot=_text(root, "plot") or _text(root, "outline"),
    )


def find_movie_nfo(video: Path) -> NfoDetails | None:
    for candidate in (video.with_suffix(".nfo"), video.parent / "movie.nfo"):
        if candidate.is_file():
            details = parse_movie_nfo(candidate.read_text(errors="replace"))
            if details is not None:
                return details
    return None
