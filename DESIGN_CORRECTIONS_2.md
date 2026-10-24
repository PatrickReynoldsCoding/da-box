# Kids TV Box: design doc CORRECTIONS 2

USB drives with any layout, one kind of video (no films or TV), Copy from USB for every drive, and posters and info set up on the box.

Found on a real Linux Mint laptop (2026-10-24) with a 1 TB Toshiba USB disk (exFAT) of everyday media.

## Status (2026-10-24)

| Item | Status | Next step |
|---|---|---|
| 1. Find media on a USB drive with any layout | Spec, decided | Build after 5 |
| 2. One kind of video: videos and groups, no films or TV | Spec, decided | With 1 |
| 3. Copy from USB for any drive | Spec (Copy from USB exists for the fixed layout) | After 1 and 2 |
| 4. Posters and info on the box: keys, fetch, fix | Spec | Answer open question 3 |
| 5. USB drive check (why a drive shows nothing) | Spec | With 1 |
| 6. Tests for many kinds of USB drive | Spec | Start now |

Already fixed in PR #3 (merged): the box did not see the disk at all (flat `lsblk` output), and it mounted it where the kid user cannot read it (`ID_BUS=ata`).

## What the drive showed us

The drive:

```
$RECYCLE.BIN/
Cloud backups/
Design/
Mortage calculator ver 2.xlsx
Music/                  351 loose .mp3 files, and 1 folder with an album
System Volume Information/
Temp/
Video/                  single videos, a series in its own folder, two "1 of 5" series, a folder of 6 shows
```

What the box showed: **2 albums**. Nothing else, because:

- The box reads only `Films/`, `TV/`, `Music/` and `Games/` at the top of the drive (DESIGN.md §8.1). `Video/` is not read.
- In `Music/` the box reads only `<Artist>/<Album>/<song>`. Loose songs are not read.
- TV shows are read only from the box's own media folder, never from a USB drive (`scan_library` in `service/dabox/library.py`: `shows=scan_shows(media_dir)`). Even a drive with `TV/` shows no TV.
- The parent sees no reason. Nothing on the TV or in the admin app says what the box found or skipped.

## Decisions (2026-10-24)

1. **No films and TV.** Telling a film from a TV episode by its name is too hard to get right. The box has one kind: **videos**. A folder with several videos is a **group** (part 2).
2. **Walk every folder** of a USB drive, to any depth.
3. **Posters and info** (part 4) are set up on the box itself, including the API keys.

## 1. Find media on a USB drive with any layout

The box must find videos, music and games **anywhere** on a USB drive, with **any** folder names. The old layout (`Films/`, `TV/`, `Music/`, `Games/`) still works, as one case of the general rule.

### 1.1 Walk the drive

1. Walk every folder on the drive, to any depth.
2. Skip system and junk folders and files:
   - `$RECYCLE.BIN`, `System Volume Information`, `.Trashes`, `.Spotlight-V100`, `.fseventsd`, `lost+found`, `@eaDir`
   - names that start with `.`, including macOS `._` files (the drive has `._BBC The Genius Of Design 2 of 5 ….avi`)
3. Keep only media files: video, audio and game files. Skip everything else (`.xlsx`, `.pdf`, photos). Keep pictures, `.nfo` and subtitle files next to media: they belong to that media.
4. The walk runs in the background. Items show on the TV as they are found. A full 1 TB drive must not block the box.
5. Cache what the walk found for each drive (by the drive's UUID, each file's path, size and modified time). The next time the drive goes in, only new or changed files are read again.

### 1.2 Music

1. Read the tags of every audio file first (artist, album artist, album, track, title). Tags win over folder names.
2. **Albums:** files with the same album artist (or artist) and album tag are one album, wherever they are on the drive.
3. **No album tag:**
   - The files in one folder (not the drive's top folder, and not a folder called `Music`) are one album, named after the folder.
   - Loose files (open question 1) go together as **"Songs on <drive label>"**, sorted by artist and title.
4. A title comes from the tag, else from the file name without the track number (`07 - Hello Goodbye.mp3` → *Hello Goodbye*; `(16) Nick Lowe - Raining Raining 1.mp3` → *Raining Raining 1*, artist *Nick Lowe*).
5. Double extensions are allowed (`20140606 131826.m4a.mp3`).

### 1.3 Games

1. A game is a file with a known extension, anywhere on the drive. Its **system** comes from the extension (or the folder name when the extension is shared):

   | System | Extensions |
   |---|---|
   | NES | `.nes` |
   | SNES | `.sfc`, `.smc` |
   | Game Boy / Color / Advance | `.gb`, `.gbc`, `.gba` |
   | Mega Drive | `.md`, `.gen`, `.smd` (`.bin` only in a folder named like Mega Drive or Genesis) |
   | PlayStation | `.cue`, `.chd`, `.pbp` (`.bin` only with its `.cue`) |

2. `.zip` files: the box looks inside. A zip with one game file is that game.
3. A game shows only if the box has a core for its system (as today).
4. The "USB games" setting still applies.

### 1.4 What does not change

- USB drives stay **read-only**. Programs on them cannot run.
- USB items keep the USB badge, go away when the drive is pulled out, are not used in channels, and can be hidden (by fingerprint).
- The limits apply to USB items.

## 2. One kind of video: videos and groups

The box stops sorting videos into films and TV. Every video is just a **video**. This applies to USB drives and to the box's own media.

### 2.1 Videos and groups

1. **A folder with one video** (and its extras: pictures, `.nfo`, subtitles) is **one video**, named after the folder.
2. **A folder with two or more videos** is a **group**, named after the folder. A group's videos play in **name order**, with numbers sorted as numbers (`Part 2` before `Part 10`).
   - Sub-folders inside a group are groups of their own, shown inside it (`Show/Season 1/`, `Show/Season 2/`).
3. **A loose video** (not in a folder, or at the top of the drive) is **one video**, named after the file.
4. A group can hold another group but nothing goes deeper than the folders on the drive: the box does not invent groups from file names.

Examples from the drive:

| On the drive | On the box |
|---|---|
| `Video/Chris Thile Mandolin - Homespun.mp4` | Video: *Chris Thile Mandolin - Homespun* |
| `Video/BBC_The_Genius_of_Design/` (5 videos) | Group: *BBC The Genius of Design*, 5 videos in order 1 of 5 … 5 of 5 |
| `Video/Guitar Heroes at the BBC, 2010, XviD (1-6)/` (6 videos) | Group: *Guitar Heroes at the BBC, 2010*, 6 videos |
| `Video/Fargo (2014) Season 5 S05 (1080p AMZN WEB-DL x265 …)/` | Group: *Fargo (2014) Season 5*, videos in episode order |

### 2.2 Clean names

Names on real drives carry release tags. The box removes them before it shows a name or looks up posters and info:

- quality and source: `1080p`, `720p`, `2160p`, `4K`, `WEB-DL`, `WEBRip`, `BluRay`, `BRRip`, `HDTV`, `PDTV`, `TVRip`, `DVDRip`, `AMZN`, `NF`
- codecs and audio: `x264`, `x265`, `HEVC`, `XviD`, `DivX`, `10bit`, `AAC`, `AC3`, `EAC3`, `DTS`, `5.1`
- release group names at the end, after the tags (`Silence`, `WatchTheBox`, `WTB`)
- dots and underscores used as spaces (`BBC_The_Genius_of_Design` → *BBC The Genius of Design*)
- in a group, the group's name at the start of each video's name (`Fargo (2014) - S05E03 - The Paradox of Intermediate Transactions` → *S05E03 - The Paradox of Intermediate Transactions*)

### 2.3 On the TV

1. The **Films** tile on Home becomes **Videos**. It shows videos and groups together, in one grid, sorted by name.
2. A group's tile shows how many videos it holds. Enter opens the group: a list of its videos (and sub-groups) in order, with **Play** (from the first not-yet-watched video) and **Play from the start**.
3. When a video in a group ends, the next one plays (the same limits apply: a video starts only if it can end before the quota and bedtime).
4. The **TV** tile (the guide and channels) does not change.

### 2.4 Channels and the box's own media

1. A channel's pool takes **videos and groups**. A group in a pool plays its videos in order (like an in-order show today).
2. The box's own media folder: what is in `Films/` and `TV/` today shows as videos and groups by the same rules. **The ids of existing films and shows stay the same**, so existing channels, hidden items, watched marks and posters keep working.
3. New media on the box (Copy from USB, upload) goes into one folder: `Videos/` (part 3). `Films/` and `TV/` are still read.

## 3. Copy from USB for any drive

Copy from USB exists (DESIGN_CORRECTIONS_1.md, "Upload"): a **USB** tile on Home in parent mode, a tick list, a space check, a background copy with progress, and "Copy to the box" on single items. Its tick list is built from the drive's `Films/`, `TV/`, `Music/`, `Games/` folders, so for this drive it shows nothing.

Changes:

1. **The tick list shows what parts 1 and 2 found**, grouped by kind: Videos (videos and groups), Albums (and the "Songs" group), Games. Not the drive's own folders.
2. **"Copy everything"** at the top of the list: one button for everything the box found that is not on the box yet. It goes through the same space check.
3. **Copy puts each item into the box's layout**, with clean names:
   - video → `Videos/<Name>/<Name>.<ext>`, with its pictures, `.nfo` and subtitles (`.srt`, `.ass`, `.sub`)
   - group → `Videos/<Group>/…`, keeping its videos' names and its sub-folders
   - album → `Music/<Artist>/<Album>/NN <Title>.<ext>`; the "Songs" group → `Music/<Artist>/Songs/…`
   - game → `Games/<system>/<file>`
4. **Already on the box** is decided by the file's fingerprint (as today), not by its name. The renamed copy is still "on the box". A group that is on the box in part gets only its missing videos.
5. Everything else stays as built: parent mode only, the space check (500 MB kept free), background job, progress bar on Home, stop, a pulled drive leaves no half item.

## 4. Posters and info on the box

**What this is:** the pictures and words the box shows for each item. For a video or group: a poster, a short description and the year. For an album: the cover. For a game: the box art. The box looks them up on the internet by the item's name (DESIGN.md §9 calls this "metadata"):

| For | Looked up on | Needs |
|---|---|---|
| Videos and groups | TMDB (The Movie Database) | A free API key from themoviedb.org |
| Albums | MusicBrainz and Cover Art Archive | Nothing |
| Games, box art | libretro-thumbnails | Nothing |
| Games, descriptions | ScreenScraper | A free ScreenScraper account (open question 3) |

Without posters and info, the box still works: it shows the name on a plain coloured tile.

Today the TMDB key can only be typed in the admin app on a phone, and nothing shows whether the look-up works (on the laptop, one album shows *not found* with no reason). DESIGN.md §4 kept keys out of the TV setup because long keys are hard to type with a controller. This part changes that decision: the parent can set it all up on the box.

### 4.1 "Posters and info" screen on the TV (parent mode)

A new button on Home in parent mode, next to "Update da-box" (open question 2).

1. **Accounts:** one row per source in the table above. Each row shows *Not needed*, *Not set*, *Working* or *Not working: <reason>*.
2. **Enter a key** in two ways:
   - **On the TV**, with the on-screen keyboard (`ui/scripts/widgets/on_screen_keyboard.gd`).
   - **From a phone:** a TMDB key is 32 characters, hard to type with a controller. The TV shows a QR code that opens the admin app's Accounts page on the phone, where the key can be pasted. The TV row updates when it is saved.
3. **Test:** after a key is saved, the box tries it at once (one TMDB request) and shows the result. A wrong key says so.
4. **Status:** how many items have posters and info, how many wait, how many were not found, and the last error (for example *TMDB: Invalid API key*, *No internet*).
5. **Look up again:** for everything not found, or for one item.
6. **Fix a wrong match** on the TV: on a video, group or album in parent mode, "Posters and info" → search by name → pick from the results. The same as the admin app does today.

### 4.2 Looking up

1. The box looks up posters and info for **USB items too** (as today), and for groups (once for the group, by its clean name).
2. Searches use the clean names (2.2). For videos and groups TMDB is searched for films and TV series together, and the best match wins. This is only to find a poster: the box does not sort the item into films or TV.
3. Errors are **kept and shown** (4.1, item 4), not only logged.
4. The look-up goes through the box's allow-list proxy, as today. The proxy must allow every source the box uses: `api.themoviedb.org`, `image.tmdb.org`, `musicbrainz.org`, `coverartarchive.org`, `archive.org`, `thumbnails.libretro.com`, `screenscraper.fr`. A test checks the list against the URLs in `service/dabox/metadata.py`.
5. Keys are stored on the box only (as today). The admin app and the TV never show a saved key again, only whether it is set and working.

## 5. USB drive check

The parent must see **why** a drive shows little or nothing. In the admin app (Home → USB sticks) and on the TV (the USB tile, parent mode), for each drive:

1. **Name, size, filesystem**, and whether it is mounted. If it is not mounted, the reason from udisks (now logged by PR #3, then shown here).
2. **Not supported:** a drive the box cannot read (HFS+/APFS from a Mac, btrfs) says so by name, instead of being silently ignored.
3. **What the box found:** videos, groups, albums, songs, games.
4. **What it skipped**, grouped: other files (spreadsheets, photos, …), games without a core, items hidden by the parent, files it could not read.
5. **While the walk runs:** "Looking for media… (N files so far)".

## 6. Tests for many kinds of USB drive

Today the tests cover the tree and flat `lsblk` outputs and the mount options. Both bugs found on the laptop were in parts with no test.

1. **Real samples.** For each kind of drive, save `lsblk -J -o PATH,FSTYPE,LABEL,UUID,MOUNTPOINT,TRAN,PKNAME` and `udevadm info -q property` output in `service/tests/drives/`, and run detection on all of them:
   - USB stick, FAT32 and exFAT
   - USB hard disk with an ATA bridge (the Toshiba: `ID_BUS=ata`)
   - USB SSD and NVMe-to-USB enclosure
   - SD card reader on USB
   - a filesystem on the whole disk, with no partition table
   - a disk with several partitions, one of them not media (swap, EFI)
   - NTFS from Windows; HFS+/APFS from a Mac (must say "not supported")
   - no label; two drives with the same label
   - flat and tree `lsblk` output for each
2. **The udev rule.** A test reads `install/files/99-dabox-usb.rules` and checks it against the `udevadm` samples: every USB sample gets `UDISKS_FILESYSTEM_SHARED=1`, the internal disk does not.
3. **The walk, groups and names** (parts 1 and 2): a sample drive built in a temp folder from real file names, including every name in this doc. Each name has its expected kind, name, group and order, album and system.
4. **Existing ids** (2.4): a box with today's `Films/` and `TV/` keeps the same ids for its films and shows after the change.
5. **Copy into the box's layout** (part 3): every kind, renamed, and found as "on the box" by fingerprint afterwards.
6. **Look-up errors** (part 4): a wrong key, no internet, a 404, and the proxy allow-list check.
7. **On a real machine** (the Mint laptop and the VM): plug in each drive kind that is to hand and check the drive check screen (part 5). Record the results in this doc.

## Plan

1. **Tests first (part 6, items 1 and 2):** collect samples from the laptop; add the udev rule test.
2. **Walk the drive (part 1) and videos and groups (part 2)**, with the drive check (part 5) to see the result.
3. **Copy from USB (part 3)** on top of parts 1 and 2.
4. **Posters and info on the box (part 4).**
5. Try each step on the laptop with the Toshiba drive. Update the status table.

## Open questions

1. **The 351 loose songs** in `Music/`: one "Songs on <drive>" group, or grouped by artist? Suggestion: by the artist tag, else by the "Artist - Title" file name, else "Songs".
2. **Where the "Posters and info" button goes:** on Home in parent mode, next to "Update da-box" (suggested)? Or a new parent "Settings" screen with both buttons?
3. **Game descriptions:** box art for games is free and needs no account (libretro-thumbnails). A short description of each game needs a ScreenScraper account (a free sign-up on screenscraper.fr), and look-ups there are slow. Is box art enough (suggested), or do you want the descriptions too?
