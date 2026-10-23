# Kids TV Box: design doc CORRECTIONS

## Status (2026-10-23)

| Item | Status | Next step |
|---|---|---|
| Next button in the setup | Done | Try it on the VM |
| Guide table in the admin app | Done | Try it on the VM |
| Copy from USB on the box | Not started | Answer the open questions, then build |
| Music: artists, songs, shuffle, search, playlists | Not started | Answer the open questions, then build |
| Loose ends | Open | See the last section |

### Try the finished work on the VM

1. `vm/box-vm.sh deploy`
2. Reset the box settings to see the setup again (back up `/var/lib/dabox`, as before).
3. On the TV: go through the setup with the keyboard only. Check Game window and Bedtime: the jump to Next, Down to Next, Left/Right between Back and Next, Up back to the table.
4. In the admin app (http://localhost:8081): Guide tab. Check the channel picker, the week picker, Shuffle week, Shuffle day, Fill again, a click on a programme, a click on an empty place.

## Next button difficult to select in the UI
This screen it is very hard to figure out how to get to the next button without a mouse. 
It seems you have to be on the bottom right of the table, press down, then press right.

In fact if you have selected "No games" on Sunday it seems impossible to even click "Next" 
Solution:
1. If the user populates all days the selector should move automatically to the next button.
2. Alternatively if the user presses down when the selector is on the last row of the table, it should move to the next button (this should already exist).
3. When the selector is on "Back" or "Next" left and right switch between them, up moves back to the mon-sun table.

Status: **done**, not yet tried on the VM. It works for every setup step (`ui/scripts/screens/setup_screen.gd`, `ui/scripts/widgets/value_picker.gd`).
- When a change sets the last empty day of a table step (Game window, Bedtime, also with "Copy Monday to every day"), the selector goes to Next. It does this only one time. A later change in the step does not jump.
- Down from the bottom of a step goes to Next. If Next is not active yet, it goes to Back.
- On Back or Next: Left and Right move between them. Up goes back to the control used last in the step.
- While a time is being changed, Down still changes the time.
- Tested with a scratch Godot test that presses the arrow keys (13 checks pass). There is no test for this in the repo yet.

![img.png](img.png)

This screen is similar. It seems impossible to use arrows to select "Next"

Same solution as above
![img_1.png](img_1.png)



## Admin app 

### Guide

Generate again should randomly generate the schedule. There should also be buttons to do this for each day. 

The view should also be better and not one long vertical list. It should be a table with days as columns and time slots as rows. Clicking a cell lets you add content

Decisions:
- One table for each channel. A channel picker at the top selects the channel.
- A programme's height in the table shows its length.
- "Shuffle day" changes only that day. The rest of the week stays.
- Shuffle changes only the channel that shows.

Spec:

1. **Top of the tab:** channel picker, week picker (Previous week, This week, Next week, and the dates of the week), and the week button (see 5 and 6).
2. **The table:**
   - 7 columns, Monday to Sunday, with the date. Today is marked.
   - A time column on the left with the hours. The table starts at the channel's earliest opening time in that week and ends at its latest closing time.
   - Each programme is a block. Its top is its start time. Its height is its length.
   - A block shows the start time, the title and the subtitle (episode or artist). A programme the parent changed has a "changed" mark. A gap the parent emptied shows as "Empty".
   - Closed hours are grey.
   - The time scale grows so that the shortest programme of the week can still be read and clicked (music tracks, short episodes). It has a limit, so a very short programme can still be small.
   - On a phone the table scrolls sideways. The time column stays on the left.
3. **Click a block:** a dialog with "Change" (pick another programme, it starts at the same time), "Empty" and "Undo" (only for a changed block). These are the actions of today's list.
4. **Click an empty place in a day:** the same dialog opens, to add a programme. It starts at the time you clicked (rounded down to 5 minutes). Programmes that the box filled in and that are under it make way. Programmes you changed or emptied never move.
5. **Shuffle (shuffle channels):** "Shuffle week" at the top, and "Shuffle day" at the top of each day column. Each press gives a new random order. Programmes you changed or emptied stay.
6. **In-order channels:** they always play in order, so there is no shuffle. There is one "Fill again" button for the week. It fills the week again (for example after new files) in the same order.
7. A shuffle is saved with the week. When the box fills the week again by itself (after a channel change, "Fill again" or "Undo"), the week and day shuffles stay. "Shuffle week" gives the whole week a new order, also the days that had their own shuffle.

Status: **done**, not yet tried on the VM.
- Service: `service/dabox/channels.py` saves the shuffles with the week (`ChannelShuffle`) and fills the week day by day. A day with its own shuffle gets its own random order. The week's order still deals through that day, so the other days do not change.
- API (`service/dabox/guide_api.py`): `GET /api/admin/guide/week?channel_id=&day=` (one channel, one week) and `POST /api/admin/guide/shuffle` (`channel_id`, `day`, `whole_week`). `POST /api/admin/guide/slots` takes a time with no time zone as the box's local time. `POST /api/admin/guide/generate` is "Fill again".
- Admin app (`service/dabox/admin_web/`): the week table. The Guide tab is wider (up to 1200 px) than the other tabs, so all 7 days show on a computer.
- Scale: from 1.6 to 12 pixels per minute, so that the shortest programme of the week is about 24 px high.
- Tests: 8 new service tests (161 pass). Checked in a browser against a dev service: shuffle day, add at a clicked time, empty, music channel, phone layout, week picker.

### Upload

Uploading one file at a time from the admin app takes too long for a hard drive full of content.
Today the box can only copy one film or one album from a USB drive at a time, and only from the admin app.

Solution: copy a USB drive to the box in one go, **on the box (the TV UI), not in the admin app**.

1. The user plugs the USB drive into the box. The drive uses the normal folder layout (`Films/`, `TV/`, `Music/`, `Games/`).
2. On the box, the user opens "Copy from USB" and sees the folders on the drive.
3. The user **ticks the folders** to copy.
4. **Before the copy starts,** the box adds up the size of the ticked folders and checks the free space on the box. If there is not enough space, the box tells the user (how much is needed, how much is free) and does not start.
5. The copy runs in the background. The box shows the progress.
6. When the copy is done, the box scans the files and fetches art and details.

Also: TV shows and games get the single-item "Copy to the box" action. Today only films and albums have it.
``
Decisions:
- "Copy from USB" shows on the box **only in parent mode**.
- The user ticks **at two levels**: tick a top folder (`Films`, `TV`, `Music`, `Games`) to copy all of it, or open it and tick single films, shows, albums or games.
- An item that is already on the box is **skipped**.
- The single-item "Copy to the box" action for TV shows and games is **on the box**.
- The box **can be used** (watch, listen, play) while the copy runs in the background.

Status: **not started**.

Plan, service:
1. **Read the drive:** an API that lists a USB drive as a tree: top folders (`Films`, `TV`, `Music`, `Games`), then the films, shows, albums and games in each, with the size of each. It marks the items that are already on the box.
2. **Space check:** an API that adds up the size of the ticked items (without the ones already on the box) and compares it with the free space on the box. If it does not fit, it says how much is needed and how much is free, and the copy does not start.
3. **Copy job:** one background job at a time. It copies item by item into the box media folder. It skips items that are already on the box. It uses the same `.partial` then rename method as `service/dabox/copying.py`, so a pulled drive leaves no half item.
4. **Progress:** an API with the job state: items done, items left, bytes done, bytes in total, the item now, skipped items, errors.
5. **When the job ends:** scan the library and fetch art and details (as after an upload).
6. **Single item copy:** extend `copy_to_box` to TV shows and games. Game saves stay, because the fingerprint comes from the file's content (`file_fingerprint` in `service/dabox/library.py`).
7. Only in parent mode: the box API refuses these calls when parent mode is off.

Plan, box UI (Godot):
1. "Copy from USB" screen: the tick list at two levels (tick a top folder, or open it and tick items). Items already on the box show as "On the box" and cannot be ticked.
2. A "Copy" button. It runs the space check first and shows the result.
3. A progress screen. The user can leave it (the copy goes on), and come back to it.
4. "Copy to the box" on a TV show and on a game (and on films and albums, if the answer to question 3 below is yes).

Plan, tests: service tests for the tree, the space check, skip, the job and parent mode. A Godot test for the tick list keys.

Open questions:
1. **Where is "Copy from USB" on the box?** For example a Home tile that shows only in parent mode, or a button on the USB badge.
2. **Where does the progress show** when the user leaves the progress screen? For example a small bar on Home, or nothing until the copy ends.
3. **Films and albums:** today "Copy to the box" for them is in the admin app. Does it also go on the box? Does it stay in the admin app?
4. **The drive is pulled out during a copy:** the job stops, the half item is removed. Does the box show a message on the TV?
5. **Parent mode is switched off during a copy:** does the copy go on?
6. **Upload tab in the admin app:** does it stay as it is?

## Music

Today the Music screen shows only albums. There is no search, no artists, no songs, no shuffle and no playlists.
DESIGN.md asks for "Albums, artists, shuffle and Now playing". Artists and shuffle are missing.

Solution: add all of these to the Music screen on the box.

1. **Artists.** A list of artists. Pick an artist to see their albums.
2. **Songs.** A list of all songs, A to Z. Pick a song to play it.
3. **Shuffle.** Shuffle one album, or shuffle all music.
4. **Search.** Use the on-screen keyboard to find an artist, an album or a song.
5. **Playlists.** A playlist is a list of songs, in an order, with a name.

Decisions:
- The user moves between Albums, Artists, Songs, Playlists and Search with a **menu**.
- **Both** the parent (in the admin app) and the kids (on the box) can make playlists.
- Playlists hold **only songs on the box**. A song on a USB drive must be copied to the box first.
- Search shows artists, albums and songs in **one result list**.
- Shuffle all does **not** include music from a USB drive.

Status: **not started**.

Plan, service:
1. **Artists:** an API with all artists (from box and USB albums), and the albums of one artist.
2. **Songs:** an API with all songs, A to Z.
3. **Search:** an API that takes text and gives one list of artists, albums and songs.
4. **Shuffle:** shuffle one album; shuffle all music on the box (not USB).
5. **Playlists:** saved in the box store. Create, rename, delete, add a song, remove a song, change the order. Only songs on the box.
6. Hidden items stay hidden in all of these (as in the album list today).

Plan, box UI (Godot):
1. A menu on the Music screen: Albums, Artists, Songs, Playlists, Search.
2. Artists screen, Songs screen, Playlists screen, one playlist screen.
3. Search screen with the on-screen keyboard (`ui/scripts/widgets/on_screen_keyboard.gd`) and one result list.
4. "Shuffle" on the album screen, and "Shuffle all music".
5. Make a playlist and add songs on the box.

Plan, admin app: Playlists: make, rename, delete, add and remove songs, change the order.

Plan, tests: service tests for each API. A Godot test for the menu keys.

Open questions:
1. **Where is the menu?** For example a row of buttons at the top of the Music screen, or a list on the left.
2. **Kids' playlists:** can a kid rename or delete any playlist, or only the ones made on the box? Can the parent delete a kid's playlist?
3. **How a kid adds a song:** from the song list ("Add to playlist"), from Now playing, or both?
4. **Naming a playlist on the box:** with the on-screen keyboard. Is there a limit on length or on the number of playlists?
5. **A song on a playlist is deleted or hidden:** remove it from the playlist, or keep it and skip it?
6. **Where is "Shuffle all music"?** For example in the menu, or on the Albums screen.

## Loose ends

In da-box:
1. **No Godot focus test in the repo.** The test for the Next button was a scratch file. Add a key-press test under `ui/tests/` if it should be kept.
2. **Old admin guide API:** `GET /api/admin/guide` (one day, all channels) is no longer used by the admin app. One test still uses it. Keep it or remove it.
3. **Emptying or placing a slot does not fill the rest of the week again.** For a shuffle channel, the next fill (Fill again, Undo, a channel change) can change later programmes of that week. This was the same before.
4. **Dev test media is very short** (1 to 4 minutes). The guide table looks crowded with it. Longer test files would show the table as it is with real content.
5. **`img_2.png` and `.idea/`** are not committed. `img_2.png` is not used in any doc.

Outside da-box (this Mac):
1. **pre-push check for work hosts** was not added (the permission check stopped the edit).
2. **Lock files from the work registry:** `betsys-shop/package-lock.json` and `js-playground/package-lock.json`.
3. **`PYTHONPATH`** in `~/.zshrc` adds two work folders for every shell.
4. **`~/.Trash/python-playground-2026-10-23`**: empty the Trash when you are sure.
