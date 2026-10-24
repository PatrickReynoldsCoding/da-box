"""Names from real drives: release tags removed, numbers sorted as numbers, "Artist - Title" split.

Pure functions only (DESIGN_CORRECTIONS_2.md, 1.2 and 2.2).
"""

import re

# Quality, source, codec and audio tags in release names. The name is cut at the first one,
# which also drops the release group name that follows them.
_TAG_WORDS = (
    r"2160p|1440p|1080p|1080i|720p|576p|480p|4k|uhd|"
    r"web[ .-]?dl|webrip|web[ .-]?rip|bluray|blu[ .-]?ray|brrip|bdrip|hdrip|hdtv|pdtv|tvrip|dvdrip|dvdscr|remux|"
    r"x264|x265|h[ .]?264|h[ .]?265|hevc|avc|xvid|divx|10bit|10-bit|8bit|hdr10|hdr|"
    r"aac2?|ac3|eac3|e-ac-3|ddp?5[ .]1|dts(?:-hd)?|truehd|atmos|[57][ .]1"
)
_TAG = re.compile(rf"(?i)(?<![\w])(?:{_TAG_WORDS})(?![\w])")
# Streaming service tags: upper case only, so a title word such as "Nf" is never cut.
_SERVICE_TAG = re.compile(r"(?<![\w])(?:AMZN|NF|DSNP|HMAX|ATVP|PCOK|iP)(?![\w])")
_BRACKETS = re.compile(r"[\(\[][^\(\)\[\]]*[\)\]]")
_SPACES = re.compile(r"\s+")
_TRAILING_SEASON_CODE = re.compile(r"(?i)\s+S\d{1,2}$")
_YEAR = re.compile(r"^(?P<title>.+?)\s*[\(\[](?P<year>(?:19[2-9]\d|20[0-4]\d))[\)\]]$")
# A bare year just before the release tags: "Some Film 2014" from "Some.Film.2014.1080p".
_YEAR_BEFORE_TAGS = re.compile(r"(?<=\s)(?P<year>(?:19[2-9]\d|20[0-4]\d))$")
_NUMBER_RUN = re.compile(r"(\d+)")
_EPISODE_MARKER = re.compile(r"(?i)(?<![a-z0-9])S(?P<season>\d{1,2})[ ._-]?E(?P<episode>\d{1,3})(?!\d)|(?<!\d)(?P<s2>\d{1,2})x(?P<e2>\d{2,3})(?!\d)")
# "07 - Song", "(16) Song", "07. Song", "07 Song": a track number of one to three digits.
_TRACK_PREFIX = re.compile(r"^\s*(?:\((?P<a>\d{1,3})\)|(?P<b>\d{1,3})(?=[\s._-]))[\s._-]*")
# A second extension left in a stem: "20140606 131826.m4a" from "20140606 131826.m4a.mp3".
_INNER_EXTENSION = re.compile(r"(?i)\.(?:mp3|m4a|aac|flac|ogg|opus|wav|wma|mp4|mkv|avi)$")


def _tidy(text: str) -> str:
    return _SPACES.sub(" ", text).strip(" -_.,;:")


def clean_name(raw: str) -> str:
    """'Fargo (2014) Season 5 S05 (1080p AMZN WEB-DL x265 …)' -> 'Fargo (2014) Season 5'."""
    text = raw.replace("_", " ")
    scene_name = " " not in text.strip()
    if scene_name:
        # Scene names use dots for spaces: "Some.Film.2014.1080p.BluRay".
        text = text.replace(".", " ")
    cut = _first_tag_position(text)
    if cut is not None:
        text = _tidy(text[:cut])
        if scene_name:
            text = _YEAR_BEFORE_TAGS.sub(r"(\g<year>)", text)
    text = _tidy(text)
    text = _TRAILING_SEASON_CODE.sub("", text)
    return _tidy(text) or _tidy(raw.replace("_", " ")) or raw


def _first_tag_position(text: str) -> int | None:
    """Where the first tag starts. A tag inside brackets cuts at the opening bracket."""
    positions = [found.start() for found in (_TAG.search(text), _SERVICE_TAG.search(text)) if found]
    if not positions:
        return None
    position = min(positions)
    # Inside an open bracket? Then cut at the outermost bracket that is still open there.
    depth, opening = 0, None
    for index, character in enumerate(text[:position]):
        if character in "([":
            if depth == 0:
                opening = index
            depth += 1
        elif character in ")]" and depth:
            depth -= 1
            if depth == 0:
                opening = None
    return opening if depth and opening is not None else position


def split_year(name: str) -> tuple[str, int | None]:
    """'Frozen (2013)' -> ('Frozen', 2013). Only a year in brackets counts: 'Blade Runner 2049' is a title."""
    match = _YEAR.match(name.strip())
    if match is None or not match.group("title").strip(" -.,"):
        return name.strip(), None
    return match.group("title").strip(" -.,"), int(match.group("year"))


def natural_key(text: str) -> list[int | str]:
    """Sorts 'Part 2' before 'Part 10', and ignores case."""
    return [int(part) if part.isdigit() else part.casefold() for part in _NUMBER_RUN.split(text)]


def episode_marker(text: str) -> tuple[int, int] | None:
    """(season, episode) from 'S05E03', 's1e2', 'S01.E02' or '1x02'."""
    match = _EPISODE_MARKER.search(text)
    if match is None:
        return None
    if match.group("season") is not None:
        return int(match.group("season")), int(match.group("episode"))
    return int(match.group("s2")), int(match.group("e2"))


def episode_marker_span(text: str) -> tuple[int, int] | None:
    match = _EPISODE_MARKER.search(text)
    return match.span() if match else None


def strip_track_number(stem: str) -> tuple[str, int | None]:
    """'07 - Hello Goodbye' -> ('Hello Goodbye', 7). A long number is a date, not a track."""
    stem = _INNER_EXTENSION.sub("", stem)
    match = _TRACK_PREFIX.match(stem)
    if match is None:
        return stem.strip(), None
    rest = stem[match.end():].strip()
    if not rest:
        return stem.strip(), None
    return rest, int(match.group("a") or match.group("b"))


def split_artist_title(stem: str) -> tuple[str | None, str]:
    """'(16) Nick Lowe - Raining Raining 1' -> ('Nick Lowe', 'Raining Raining 1')."""
    title, _ = strip_track_number(stem)
    artist, separator, rest = title.partition(" - ")
    if separator and artist.strip() and rest.strip() and not artist.strip().isdigit():
        return artist.strip(), rest.strip()
    return None, title


def without_common_start(names: list[str]) -> list[str]:
    """Removes the words every name starts with ('BBC The Genius Of Design 1 of 5 …' ->
    '1 of 5 …'), when at least two names share them and something is left of each."""
    if len(names) < 2:
        return names
    split = [name.split(" ") for name in names]
    shared = 0
    for words in zip(*split):
        if len({word.casefold() for word in words}) != 1:
            break
        shared += 1
    if shared == 0 or any(len(words) <= shared for words in split):
        return names
    return [_tidy(" ".join(words[shared:])) or name for words, name in zip(split, names)]
