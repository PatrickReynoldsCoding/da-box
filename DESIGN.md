# Kids TV Box: design doc

Status: draft 5. Date: 2026-10-22.

## 1. Summary

The box is a Linux machine (Raspberry Pi 5 or x86 mini PC) that connects to the TV. It does these things only:

1. Plays films, shows and music from the box or a USB stick.
2. Shows a weekly TV guide with live-style video channels and music channels.
3. Plays retro games with RetroArch during a game window, and saves the game before it closes.

A shared daily quota, an overrun allowance and a bedtime control screen time. A PIN-locked admin web page, on the home Wi-Fi only, controls everything. Parent mode unlocks everything.

## 2. Goals and non-goals

| Goals | Non-goals |
|---|---|
| A fun UI for arrow keys, Enter and Esc, or a game controller | Web browser, app store or online content |
| TV guide with live-style video and music channels | Streaming of any kind (online services or PC game streaming) |
| Films, shows, music and games from the box or USB | Profiles for each child |
| Games in a game window, with auto-save | Control from outside the home network |
| Quota, overrun allowance and bedtime | More than one box |
| First-run setup on the TV | |

## 3. Hardware

All parts run on any Debian-based Linux machine. One installer supports both targets.

| | Raspberry Pi 5 | x86 mini PC (for example Intel N100) |
|---|---|---|
| Price | Low | Medium |
| Retro games | Good up to PS1, N64 and some Dreamcast | Good up to PS2 and GameCube |
| Video | Good for 1080p. Good for most 4K. | Good for 4K |
| Clock when power is off | Needs an extra small battery (NTP sets the time when online) | Has a clock battery already |

## 4. First-run setup (on the TV)

At first start-up, the box shows setup screens on the TV. The parent uses the controller or the keyboard. The parent picks each setting.

| Step | Setting |
|---|---|
| 1 | Welcome screen |
| 2 | Network: Wi-Fi (on-screen keyboard) or Ethernet |
| 3 | Admin PIN (enter two times) |
| 4 | Time zone |
| 5 | Daily quota |
| 6 | Shared quota for video + games (ON or OFF) |
| 7 | Overrun allowance, n minutes |
| 8 | Game window, for each day of the week |
| 9 | Bedtime, for each day of the week |
| 10 | Overrun allowance at bedtime (yes or no) |
| 11 | USB playback (ON or OFF) and USB games (ON or OFF) |
| 12 | Done. The TV shows a QR code and `http://tvbox.local` for the admin app. |

Notes:

- Metadata accounts and API keys are not in the TV setup, because long keys are hard to type with a controller. The parent adds them later in the admin app.
- All settings can be changed later in the admin app.
- The admin app can run the TV setup again.

## 5. Modes

| | **Kid mode** (default) | **Parent mode** |
|---|---|---|
| Content | Visible items only | All items |
| Games | Game window only | Any time |
| Quota and bedtime | On | Off |
| Turn on | Always on at start-up | **Admin app only** |
| Turn off | n/a | "Leave parent mode" on the box, the admin app, or shut-down |

Parent mode has no auto-off timer. A badge shows on screen while parent mode is on.

## 6. Box UI

### 6.1 Controls

| Action | Keyboard | Controller |
|---|---|---|
| Move | Arrow keys | D-pad or left stick |
| Select | Enter | A |
| Back | Esc | B |
| Leave a game | Esc (held) | Select + Start (held) |

There are no other buttons. Every screen works with these inputs only.

### 6.2 Screens

1. **Home.** Tiles: **TV**, **Films**, **Music**, **Games**. Each tile shows the time left, or the opening time for games.
2. **TV guide.** Video channels, music channels and a "Game Time" row. A "Bedtime" line. Programmes that cannot finish in the time left are greyed out.
3. **Channel playback.** Starts at the current point in the schedule. Up and Down change the channel.
4. **Films.** Poster grid. Films that cannot finish in the time left are greyed out.
5. **Music.** Albums, artists, shuffle and "Now playing" with album art.
6. **Games.** Box art grid. Greyed out when games are closed. "Continue" loads the last save.
7. **Warnings.** At 5 minutes and 1 minute before the game window ends or bedtime.
8. **TV is sleeping.** After the quota or bedtime.

There is no USB tile. USB items show in the normal screens with a small USB badge.

### 6.3 Making it fun

Bright colours, big tiles, sounds when the child moves and selects, small animations and a mascot.

## 7. Rules

### 7.1 Channels

- **Video channels** and **music channels** both use the live-style schedule.
- Each channel has a content pool and rules, for example "Show X in order", "random films 18:00–20:00" or "Bedtime songs 19:00–19:30".
- The generator fills one week. It does not overwrite hand-edited slots.
- Playback starts at `now − slot start time`, so a programme can start part-way through, like real TV.
- Gaps show a "Back soon!" screen.
- USB items are **not** used in channels, because a stick can be removed at any time.

### 7.2 Game window

- Set for each day of the week.
- Games can start only inside the window.
- At the end: warnings, then **save state**, then close RetroArch.
- The parent can add extra time for today only.

### 7.3 Quota

- **Shared quota ON (default):** video and games use one daily quota.
- **Shared quota OFF:** the quota counts video only. Games are limited by the game window only.
- **Music never counts,** including music channels.
- The box counts time only while video or a game plays.
- The used time is saved, so a restart does not reset it. It resets at midnight.
- The parent can add extra time for today only.

### 7.4 Overrun allowance

- Setting: **n minutes, default 20.**
- A video item **can start only if it ends before quota end + n minutes.**
- For channels, the box uses the time left in the current programme.
- Because of this rule, video always ends normally. It does not stop in the middle.
- Games get no overrun. They save and close when the quota or the game window ends.

### 7.5 Bedtime

- Set for each day of the week.
- The overrun allowance at bedtime is a setting.
- At bedtime: warnings, then video stops, games save and close, and the box shuts down.

### 7.6 After the quota

- The box shows "TV is sleeping until tomorrow", then it shuts down.
- If the box is turned on again the same day, video is locked. Music works. Games work if the game window is open and the rules allow it (with shared quota ON, games also need quota).

## 8. USB sticks

### 8.1 Folder layout

```
USB stick/
├── Films/
│   └── Frozen (2013)/
│       ├── Frozen (2013).mkv
│       ├── poster.jpg          (optional)
│       └── movie.nfo           (optional)
├── TV/
│   └── Bluey/
│       └── Season 01/
│           └── Bluey S01E01.mp4
├── Music/
│   └── Artist/
│       └── Album/
│           └── 01 Song.mp3
└── Games/
    ├── snes/
    │   └── Super Mario World.sfc
    ├── gba/
    └── psx/
```

The admin app shows the list of supported game folder names, for example `nes`, `snes`, `gba`, `megadrive`, `n64` and `psx`.

### 8.2 Behaviour

- When a stick goes in, the box mounts it **read-only**, and programs on the stick cannot run.
- Its items **merge** into Films, TV, Music and Games, with a USB badge.
- When the stick comes out, its items go away.
- Art and metadata come from the `.nfo` files and images on the stick. If there are none, the box fetches them automatically. The box keeps them in a cache, so the stick is fast the next time.
- The parent can hide a USB item. The box remembers it by the file's fingerprint (hash), so it stays hidden the next time.
- Game saves for USB games are stored **on the box**, keyed by the file's fingerprint.
- The quota and all other rules apply to USB items.
- The admin app can copy USB items to the box permanently.

## 9. Metadata

- **Automatic:** when new media arrives (upload, USB import or USB stick), the service fetches art and details.
- **Admin app:** add accounts and API keys. For each item, pick from the available posters, backgrounds and box art, fix a wrong match, or edit by hand.

| Media | Source | Note |
|---|---|---|
| Films and TV | TMDB | Free for personal use. Needs a free API key. |
| Music | Tags in the file, then MusicBrainz + Cover Art Archive | Free. No key. |
| Games | libretro-thumbnails (box art), ScreenScraper (descriptions) | ScreenScraper needs a free account. |
| Offline | `.nfo` files and images next to the media (Kodi format) | For media prepared on a PC. |

## 10. RetroArch

- Runs in kiosk mode with a password.
- The service controls it through the RetroArch command port (localhost only).
- **Before it closes a game,** the service sends "save state", waits until the save is done, then sends "quit".
- When the child opens the game again, RetroArch loads that save automatically ("Continue").
- In-game saves (SRAM) are kept too.
- Some cores do not support save states well. Test each core before use.

## 11. Admin app

Open `http://tvbox.local` on a phone or computer on the home Wi-Fi. Enter the PIN.

| Area | What the parent can do |
|---|---|
| **Parent mode** | Turn it on or off. |
| **Content** | Upload, import or copy from USB, mark items visible or hidden. |
| **Metadata** | Accounts and API keys, automatic fetch, pick art, fix matches, edit by hand. |
| **Channels** | Video and music channels, rules and hours. |
| **TV guide** | See and edit the week. Generate again. |
| **Limits** | Quota, shared quota, overrun n, game window, bedtime, bedtime overrun, extra time today. |
| **USB** | USB playback on/off, USB games on/off, list of game folder names. |
| **Settings** | PIN, time zone, Wi-Fi, software update, backup, run the TV setup again. |
| **Activity** | What was watched, played and listened to, and for how long. |

## 12. Architecture

```
┌──────────────── Linux machine (Pi 5 or x86, Debian based) ────────────┐
│                                                                       │
│  user "kid"  ── firewall: localhost only, no network ──               │
│    cage (kiosk)                                                       │
│     └── Box UI (Godot 4)  + first-run setup screens                   │
│            ├── mpv        → video and music                           │
│            └── RetroArch  → games (kiosk mode, localhost command port)│
│                                                                       │
│  user "tvbox" ── firewall: home network + metadata allow-list ──      │
│    Box service (Python, FastAPI)                                      │
│     ├── SQLite                                                        │
│     ├── Guide generator (video + music channels)                      │
│     ├── Limit enforcer (quota, overrun, game window, bedtime)         │
│     ├── RetroArch control (save state → quit)                         │
│     ├── Metadata fetcher (automatic) + art cache                      │
│     ├── USB watcher (read-only mount, merge, unmerge)                 │
│     └── Admin web app + API                                           │
│                                                                       │
│  system ── firewall: NTP; update servers only during an update        │
│  /media  (films, shows, music, games, art, saves)                     │
└───────────────────────────────────────────────────────────────────────┘
```

### 12.1 Why these parts

| Part | Choice | Reason |
|---|---|---|
| OS | Debian based, no desktop (Raspberry Pi OS Lite on the Pi) | No desktop, browser or file manager to remove. |
| Kiosk | `cage` | Shows one app full screen. Restarts it if it stops. Nothing to exit to. |
| Box UI | Godot 4 | Good for a fun, animated UI. Good controller support. Runs on the Pi 5. It is **not** a browser engine. |
| Video and music | mpv | Plays almost all formats. Hardware decoding. The UI controls it by IPC. |
| Games | RetroArch | Kiosk mode, command line, command port. |
| Service + admin | Python (FastAPI) + SQLite | Light work, fast enough on a Pi 5, preferred language. |

The **service** enforces all limits. If the UI crashes, the limits stay in force.

## 13. Lock-down plan

1. **Firewall for each user:** `kid` has no network. `tvbox` reaches the home network and the metadata allow-list only. The system reaches NTP, and the update servers only during a parent-started update.
2. **No browser** package is installed. The admin app opens in the parent's browser, not on the box.
3. **No exit:** the box starts straight into the kiosk. Console logins (TTYs) are off.
4. **RetroArch:** kiosk mode with a password. Online updater, core downloader, netplay, achievements and file browser are off. Command port on localhost only.
5. **mpv:** local files only. Network streams are off.
6. **USB:** read-only, and programs on the stick cannot run.
7. **Admin:** PIN with lockout after wrong tries. Home network only.

## 14. Build phases

| Phase | Result |
|---|---|
| **1. Base box** | Installer (Pi 5 + x86), kiosk boot, firewall for each user, Home, Films and Music. |
| **2. Setup + admin** | TV setup screens, PIN, admin app, upload, visible/hidden, parent mode. |
| **3. USB + metadata** | Folder layout, merge, automatic fetch, art picker. |
| **4. Channels + guide** | Video and music channels, generator, guide, live-style playback. |
| **5. Limits + games** | RetroArch, save then quit, quota, overrun rule, game window, bedtime, sleeping screen. |
| **6. Polish** | Themes, sounds, mascot, activity log, backup, updates. |

## 15. Decisions log

| # | Decision |
|---|---|
| 1 | Linux only. Raspberry Pi 5 or x86 mini PC. |
| 2 | No streaming of any kind. |
| 3 | Admin app on the home Wi-Fi only. |
| 4 | No profiles. Parent mode instead, turned on from the admin app only. |
| 5 | Parent mode has no auto-off. It turns off on the box, in the admin app, or at shut-down. |
| 6 | Channels play live-style (part-way through). |
| 7 | Games use a time window. |
| 8 | Shared quota for video + games is a setting, ON by default. |
| 9 | Music has no limit. |
| 10 | A video item can start only if it ends before quota end + n minutes (n default 20). |
| 11 | Bedtime per day. Bedtime overrun is a setting. |
| 12 | After the quota, the box sleeps. On restart, video stays locked for the day. |
| 13 | RetroArch saves state before it closes. |
| 14 | USB: fixed folder layout, merged into libraries, read-only. Playback and games ON by default. Not used in channels. Hidden USB items are remembered by hash. |
| 15 | Metadata fetched automatically. Accounts and art picking in the admin app. |
| 16 | Firewall for each user. NTP allowed. |
| 17 | Service written in Python. |
| 18 | First-run setup runs on the TV. Metadata accounts are added later in the admin app. |
