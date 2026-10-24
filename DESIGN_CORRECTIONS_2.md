# Kids TV Box: design doc CORRECTIONS 2

USB drives with any layout, one kind of video (no films or TV), Copy from USB for every drive, posters and info set up on the box, a Settings screen on the box, removing da-box from the admin app, and a power menu.

Found on a real Linux Mint laptop (2026-10-24) with a 1 TB Toshiba USB disk (exFAT) of everyday media.

## Status (2026-10-24)

| Item | Status | Next step |
|---|---|---|
| 1. Find media on a USB drive with any layout | Done, tests with the real drive's names | Try it on the laptop with the Toshiba drive |
| 2. One kind of video: videos and groups, no films or TV | Done, service and key tests | Try it on the laptop |
| 3. Copy from USB for any drive | Done, service and key tests | Try it on the laptop |
| 4. Posters and info on the box: keys, fetch, fix | Done, service and key tests. ScreenScraper tested with a fake server only | Try it on the laptop with a TMDB key |
| 5. USB drive check (why a drive shows nothing) | Done, service and key tests | Try it on the laptop |
| 6. Tests for many kinds of USB drive | Done: 12 drive samples (2 real), udev rule test | Record more real drives |
| 7. Settings screen on the box (Update da-box, Posters and info) | Done, tried on the laptop. Posters and info is a placeholder until part 4 | Part 4 |
| 8. Remove da-box from the admin app (back to plain Linux) | Done, tests in the repo | Try it on the laptop (it removes da-box) |
| 9. Power menu: Esc on Home or the Guide button, then Shut down | Spec, decided | With 1 to 4 |

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
3. **Posters and info** (part 4) are set up on the box itself, including the API keys. ScreenScraper (game descriptions) is an **option**, next to TMDB.
4. **Songs without tags are grouped like iTunes:** by artist and album, with *Unknown Artist* and *Unknown Album* for what is missing.
5. **A Settings screen on the box** (part 7) holds Update da-box and Posters and info. It does **not** need parent mode: anyone can use it. It is out of the way (not a big tile on Home), so kids do not press it by accident.
6. **No automatic updates.** A person presses Update da-box.
7. **The admin app can remove da-box** and give the machine back as plain Linux (part 8).
8. **A power menu** on the TV (part 9), with one choice for now: Shut down.

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
3. **Missing tags, like iTunes:** each song gets an artist and an album, in this order:
   - **Artist:** the artist tag; else the "Artist - Title" file name (`(16) Nick Lowe - Raining Raining 1.mp3` → *Nick Lowe*); else **Unknown Artist**.
   - **Album:** the album tag; else **Unknown Album**. The folder name is not used as the album: on this drive 351 songs sit in one folder called `Music`.
   - Songs then group into albums as in 2: one *Unknown Album* for each artist, and *Unknown Artist – Unknown Album* for songs with neither.
4. A title comes from the tag, else from the file name without the track number and the artist (`07 - Hello Goodbye.mp3` → *Hello Goodbye*; `(16) Nick Lowe - Raining Raining 1.mp3` → *Raining Raining 1*).
5. Double extensions are allowed (`20140606 131826.m4a.mp3`).
6. Artists, Songs, Search and Shuffle all (DESIGN_CORRECTIONS_1.md, Music) see these songs the same as tagged ones.

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

1. **The tick list shows what parts 1 and 2 found**, grouped by kind: Videos (videos and groups), Albums, Games. Not the drive's own folders.
2. **"Copy everything"** at the top of the list: one button for everything the box found that is not on the box yet. It goes through the same space check.
3. **Copy puts each item into the box's layout**, with clean names:
   - video → `Videos/<Name>/<Name>.<ext>`, with its pictures, `.nfo` and subtitles (`.srt`, `.ass`, `.sub`)
   - group → `Videos/<Group>/…`, keeping its videos' names and its sub-folders
   - album → `Music/<Artist>/<Album>/NN <Title>.<ext>`, also for *Unknown Artist* and *Unknown Album*
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
| Games, descriptions (optional) | ScreenScraper | A free account on screenscraper.fr. Without it, games get box art only. |

Without posters and info, the box still works: it shows the name on a plain coloured tile.

Today the TMDB key can only be typed in the admin app on a phone, and nothing shows whether the look-up works (on the laptop, one album shows *not found* with no reason). DESIGN.md §4 kept keys out of the TV setup because long keys are hard to type with a controller. This part changes that decision: the parent can set it all up on the box.

### 4.1 Posters and info, in Settings on the TV

A section of the Settings screen (part 7). No parent mode needed.

1. **Accounts:** one row per source in the table above. Each row shows *Not needed*, *Not set*, *Working* or *Not working: <reason>*. ScreenScraper has a user name and a password.
2. **Enter a key** in two ways:
   - **On the TV**, with the on-screen keyboard (`ui/scripts/widgets/on_screen_keyboard.gd`).
   - **From a phone:** a TMDB key is 32 characters, hard to type with a controller. The TV shows a QR code that opens the admin app's Accounts page on the phone, where the key can be pasted. The TV row updates when it is saved.
3. **Test:** after a key is saved, the box tries it at once (one TMDB request) and shows the result. A wrong key says so.
4. **Status:** how many items have posters and info, how many wait, how many were not found, and the last error (for example *TMDB: Invalid API key*, *No internet*).
5. **Look up now** (the scrape button): looks up everything that has no posters and info yet, and everything that was not found before. The status above shows its progress.
6. **Fix a wrong match** on the TV: on a video, group or album in parent mode, "Posters and info" → search by name → pick from the results. The same as the admin app does today. (This one stays in parent mode: it changes what the kids see.)

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

## 7. Settings screen on the box

One place on the TV for box settings that anyone may use, out of the kids' way.

1. **Where:** a small **Settings** button (a gear) at the bottom right of Home, not a big tile. It is always there, also when parent mode is off.
2. **Inside, in this order:**
   1. **Update da-box** (moved from Home's parent-mode row, PR #2): installed and newest version, Check again, Update.
   2. **Posters and info** (part 4): accounts, status, Look up now.
   3. **About:** the version, the box's address (`http://tvbox.local`) and a QR code for the admin app.
3. **No parent mode needed.** The box API for these (`/box/software/*` today) moves from the parent-mode router to the plain box router. It stays **box only** (localhost): the network cannot use it.
4. **Kids do not press it by accident:** the Settings button is small and last in the focus order on Home (Down from the tiles reaches it only after the other buttons). Update da-box and Look up now each ask "Are you sure?" with **No** focused first.
5. The admin app keeps its own Update and Accounts (as today).

## 8. Remove da-box from the admin app

A way to give the machine back as plain Linux, without a terminal. Only in the **admin app** (PIN), never on the TV.

1. **Where:** Settings → a last card, **Remove da-box**, in a warning colour.
2. **Two choices:**
   - **Remove da-box, keep the media:** the films, music and games stay in `/srv/dabox/media`, readable from Linux.
   - **Remove everything:** also deletes the media, settings, and the `kid` and `tvbox` users (`uninstall.sh --purge`).
3. **Confirm:** the parent types the PIN again and the word `REMOVE`. The card says what will happen: the TV turns off da-box, and the machine restarts into its normal Linux login screen.
4. **What runs:** a root unit, `dabox-remove.service`, started by the service (polkit allows that one unit, as for the updates). It runs `install/uninstall.sh` (with `--purge` for "Remove everything"), then restarts the machine.
   - `install.sh` must copy `uninstall.sh` onto the box (`/opt/dabox/bin/dabox-uninstall`). Today it is only in the git checkout.
   - It must work while `--purge` deletes `/opt/dabox` itself (the update script has the same problem and the same fix: everything in functions).
5. **What comes back** (what `uninstall.sh` does today, plus two gaps it has):
   - the desktop login screen and other firewalls that the installer turned off (`/etc/dabox/turned-off`), the login consoles, SSH as before
   - **new:** the machine's **old name**. The installer renames it `tvbox`; it must save the old name (`/etc/dabox/hostname-before`) and `uninstall.sh` must set it again.
   - **new:** the **default target** before the install (`graphical.target` or `multi-user.target`).
6. **After it:** the admin app shows "da-box is being removed. The machine restarts into Linux in about a minute." It cannot show more: the admin app goes away with da-box.
7. **Tests:** service tests for the PIN and `REMOVE` check and for starting the unit (with a fake runner). On the Mint laptop: remove, check the desktop and the old name come back, then install again.

## 9. Power menu

A way to turn the box off from the TV, without a keyboard or the power button.

1. **Open it:**
   - **Esc** (keyboard) or **B** (controller) **on Home**. Home has nothing to go back to, so Back there opens the power menu.
   - The controller's **Guide button** on **any screen**: the Xbox button, the PlayStation button, the Home button on 8BitDo and Nintendo-style pads (Godot: `JOY_BUTTON_GUIDE`).
   - Not while a video or game plays: there the Guide button does nothing. Videos stop with B; games quit through RetroArch's own combo.
2. **What it shows:** a small panel over the screen with **Shut down** and **Cancel**. **Cancel** has the focus first, so a kid who opens it by accident does not turn the box off. B or Esc means Cancel.
3. **Shut down** asks the service to turn the box off (`POST /box/power/off`, box only, any user; the service already may power off through polkit, for bedtime). Before that the TV shows "Turning off…".
4. No parent mode needed: anyone may turn the TV box off.
5. **Later:** more choices can go in this menu (Restart, Sleep). Only Shut down for now.
6. **Tests:** key tests for Esc on Home, the Guide button on another screen, Cancel focused first, B means Cancel; a service test that the route calls the power backend and that the network cannot use it.

## Plan

1. **Settings screen (part 7)** with Update da-box moved into it, and **Remove da-box (part 8)**: small, and they change things already built.
2. **Tests for USB drives (part 6, items 1 and 2):** collect samples from the laptop; add the udev rule test.
3. **Walk the drive (part 1) and videos and groups (part 2)**, with the drive check (part 5) to see the result.
4. **Copy from USB (part 3)** on top of parts 1 and 2.
5. **Posters and info (part 4)**, in the Settings screen.
6. **Power menu (part 9).**
7. Try each step on the laptop with the Toshiba drive. Update the status table.

## Open questions

None at the moment (answered 2026-10-24).

## Status notes

**Part 7, Settings screen (2026-10-24): done**, tried on the Mint laptop: Settings opens from Home, and Down and Up scroll it.
- Home: a small Settings button (gear) at the bottom right, next to the mascot, with or without parent mode. Update da-box left the parent-mode row.
- `ui/scripts/screens/settings_screen.gd` (was `software_screen.gd`): Update da-box, Posters and info (a note until part 4), About (version, admin app addresses and QR code).
- Update asks "Are you sure?" with **No** focused; Esc or B on the question means No.
- Service: `/box/software/*` moved from the parent-mode router to the box router (box only, no parent mode). Tests: the TV updates without parent mode; the network still cannot.
- Down and Up scroll the Settings screen when there is nothing to focus below or above (the text-only Posters and info and About): `key_scroll` in `ui/scripts/screens/screen.gd`, for any screen.
- Key tests: Settings opens from Home without parent mode; Update asks first with No focused; Back on the question means No; Down scrolls to the bottom and Up back to the top.

**Part 8, Remove da-box (2026-10-24): done**, not yet tried on a real machine.
- Admin app: Settings → Remove da-box (last card): keep the media or remove everything, the PIN again and the word REMOVE, then a browser "Are you sure?".
- Service: `POST /api/admin/remove-dabox` (`maintenance_api.py`). A wrong PIN here counts towards the login lockout. It starts `dabox-remove@keep` or `dabox-remove@purge` (`SystemdRemover` in `maintenance.py`), which polkit allows for the service user only.
- `install.sh` installs `uninstall.sh` as `/opt/dabox/bin/dabox-uninstall` and the unit `dabox-remove@.service`, and saves the machine's name (`/etc/dabox/hostname-before`) and default target (`/etc/dabox/target-before`) before it changes them.
- `uninstall.sh`: new `--reboot`; gives the name and target back; runs from functions, so `--purge` can delete it while it runs.
- Tests: the word, the PIN, the lockout, keep and purge (fake runner), the admin login. The polkit rule checked with node. The new restore steps dry-run with fake commands.
- A machine renamed to `tvbox` by an older install (the Mint laptop) has no saved old name: it stays `tvbox` after removal. Rename it with `sudo hostnamectl set-hostname <name>`.

**Part 6, USB drive tests (2026-10-24): done.**
- `service/tests/drives/`: 12 samples, one per kind of drive in 6.1. Two are real: the Mint laptop with the Toshiba disk (`ID_BUS=ata`, flat `lsblk`), and the Yoga PC with an empty USB card reader and 22 snap loop devices. The rest are typical; replace them with real recordings when those drives are to hand (`tests/drives/README.md`).
- `tests/test_usb_drives.py`: for every sample, the partitions found, the ones named "not supported" (new: `unsupported_usb_filesystems` in `usb.py`), one id per drive, and the udev rule (a small udev evaluator reads `99-dabox-usb.rules`).
- Checked that the tests catch both bugs from the laptop: the old `ID_BUS==usb` rule fails 4 tests, and detection without `PKNAME` fails 8.

**Parts 1, 2, 3 and 5 (2026-10-24): done**, not yet tried on the laptop.
- `service/dabox/names.py`: clean names, natural order, episode markers, track numbers, "Artist - Title". `tests/test_names.py` uses the real names from the Toshiba drive.
- `service/dabox/library.py` walks every folder. A video in its own folder is named after it; several videos make a group (`Show` in the code, so box TV shows keep their ids); section folders (`Season 1`, `S02`, `Disc 1`, `Extras`) stay inside the group; generic folders (`Video`, `Films`, `TV`, `Temp`, …) are never one item. In the box's own `TV/`, every folder is a group, as before. Songs group by artist and album tags, like iTunes; folder names count only in `Music/<Artist>/<Album>/`. Games by extension, a zip with one game, a `.cue` that points at `.bin` files, a `.bin` in a Mega Drive folder. Each scan writes a report (found, other files, system folders, unreadable).
- Decided while building: a video in a group keeps its title after the marker ("The Paradox of Intermediate Transactions") and shows its code beside it ("S5 E3"); only bracketed years count (`Blade Runner 2049` is a title), except in dotted scene names; a folder called `Series` or `Shows` is generic.
- The walk runs in the background (the USB watcher), but not yet item by item: a drive's items show when its walk ends. The cache is the file fingerprints and durations, not a saved walk.
- Box API: `GET /box/videos` (videos and groups), `GET /box/groups/{id}`, `POST /box/groups/{id}/resume`. Channels use box groups only. The admin app lists groups under Videos and can hide them.
- TV: the Home tile is **Videos**; `videos_screen.gd` (was `films_screen.gd`) and `group_screen.gd` (Play, Play from the start, sections; the next video plays when one ends, if the limits allow it).
- Copy from USB: the tick list by kind; **Copy everything**; copies go to `Videos/<name>/`, `Music/<artist>/<album>/NN <title>`, `Games/<system>/`; a different item with the same name gets " (2)"; a group on the box in part is finished in its own folder; groups keep their hidden state.
- Drive check: `GET /box/usb/drives` and `/api/admin/usb/drives` (`drive_check.py`); udisks mount errors are kept and a failed drive is tried again after a minute; on the TV at the top of Copy from USB, in the admin app on Home.

**Part 4, Posters and info (2026-10-24): done**, not yet tried on the laptop.
- TMDB searches films and TV series together; a group prefers TV series, and an exact title comes first. "Fargo (2014) Season 5" is searched as "Fargo", 2014 (`search_terms`). TMDB ids say their kind (`movie:1`, `tv:7`); older records with the bare film id still work.
- Groups get posters and info like videos, in the background and in the admin app.
- Keys are tried when saved (TMDB `/configuration`, ScreenScraper `ssuserInfos.php`); each source is *No key needed*, *Not set*, *Working* or *Not working: <reason>*. A failed look-up keeps its reason; the last one shows in Settings.
- ScreenScraper (optional) adds a game's name, year and description to the libretro box art. Its API needs a developer id and password as well as the user's account, so Settings asks for all four. Tested with a fake ScreenScraper only.
- Routes: `GET /box/posters`, `PUT /box/posters/accounts`, `POST /box/posters/lookup` (box only, no parent mode), the same under `/api/admin/posters`; fix a match on the TV: `POST /box/content/{id}/metadata/search` and `/apply` (parent mode). `/box/admin-qr.png?target=accounts` opens the admin app's key form.
- A test checks that the proxy allow-list (`install/files/dabox-filter`) lets every source through.
- TV: Settings → Posters and info (sources, Enter TMDB key, ScreenScraper account, Use a phone, the counts, Look up now with "Are you sure?"); `text_entry_screen.gd`; `match_screen.gd` from "Posters and info" on a video (parent mode, `item_actions_screen.gd`, was `usb_item_screen.gd`), a group or an album.
- Admin app: Settings → Posters and info, with the sources, the counts, Look up now and the ScreenScraper fields; groups open the details dialog like videos.
