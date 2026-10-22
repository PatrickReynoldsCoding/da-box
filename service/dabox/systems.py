"""Game systems: the folder name under Games/, the file types, and the libretro core."""

from pathlib import Path

from pydantic import BaseModel


class GameSystem(BaseModel):
    key: str
    name: str
    extensions: frozenset[str]
    core: str
    # Folder name on thumbnails.libretro.com.
    thumbnails_name: str


_CARTRIDGE_ZIP = frozenset({".zip"})

SYSTEMS: dict[str, GameSystem] = {
    system.key: system
    for system in [
        GameSystem(key="nes", name="NES", extensions=frozenset({".nes"}) | _CARTRIDGE_ZIP,
                   core="nestopia_libretro.so", thumbnails_name="Nintendo - Nintendo Entertainment System"),
        GameSystem(key="snes", name="Super Nintendo", extensions=frozenset({".sfc", ".smc"}) | _CARTRIDGE_ZIP,
                   core="bsnes_mercury_performance_libretro.so", thumbnails_name="Nintendo - Super Nintendo Entertainment System"),
        GameSystem(key="gb", name="Game Boy", extensions=frozenset({".gb"}) | _CARTRIDGE_ZIP,
                   core="gambatte_libretro.so", thumbnails_name="Nintendo - Game Boy"),
        GameSystem(key="gbc", name="Game Boy Color", extensions=frozenset({".gbc"}) | _CARTRIDGE_ZIP,
                   core="gambatte_libretro.so", thumbnails_name="Nintendo - Game Boy Color"),
        GameSystem(key="gba", name="Game Boy Advance", extensions=frozenset({".gba"}) | _CARTRIDGE_ZIP,
                   core="mgba_libretro.so", thumbnails_name="Nintendo - Game Boy Advance"),
        GameSystem(key="megadrive", name="Mega Drive", extensions=frozenset({".md", ".gen", ".smd", ".bin"}) | _CARTRIDGE_ZIP,
                   core="genesis_plus_gx_libretro.so", thumbnails_name="Sega - Mega Drive - Genesis"),
        GameSystem(key="psx", name="PlayStation", extensions=frozenset({".cue", ".chd", ".pbp"}),
                   core="pcsx_rearmed_libretro.so", thumbnails_name="Sony - PlayStation"),
    ]
}


def find_core(system: GameSystem, core_dirs: list[Path]) -> Path | None:
    for folder in core_dirs:
        candidate = folder / system.core
        if candidate.is_file():
            return candidate
    return None


def thumbnail_file_name(title: str) -> str:
    """libretro-thumbnails replaces these characters with "_" in file names."""
    for character in '&*/:`<>?\\|"':
        title = title.replace(character, "_")
    return title
