extends Node
## Key-press tests: arrow keys, Enter and focus, like a parent or kid with a controller.
## No service or agent needed (Api.offline): each test gives the screen its data.
##
## Run: godot --headless --path ui res://tests/key_tests.tscn
## Prints each failed check and quits with exit code 1 if any failed.

var _checks := 0
var _failures := 0
var _layer: Control


func _ready() -> void:
	Api.offline = true
	_layer = Control.new()
	_layer.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_layer.theme = UiTheme.build()
	add_child(_layer)
	_run.call_deferred()


func _run() -> void:
	await _test_setup_jumps_to_next()
	await _test_setup_down_goes_to_back()
	await _test_copy_tick_list()
	await _test_copy_everything_and_drive_check()
	await _test_music_menu()
	await _test_music_screens_open()
	await _test_controller_buttons()
	await _test_home_settings_button()
	await _test_settings_update_asks_first()
	await _test_videos_tiles()
	await _test_group_screen()
	await _test_posters_settings()
	await _test_match_screen()
	print("Key tests: %d checks, %d failed" % [_checks, _failures])
	get_tree().quit(1 if _failures > 0 else 0)


# ---- Setup: the Next button (DESIGN_CORRECTIONS_1.md, "Next button difficult to select") ----

func _test_setup_jumps_to_next() -> void:
	var setup := SetupScreen.new()
	await _show(setup)
	setup._show_step(7)
	await _frames()
	_check(_focus() is Button and (_focus() as Button).text == "Copy Monday to every day", "game window: starts on Copy Monday")

	for day in SetupScreen.DAYS:
		var no_games := (setup._game_rows[day[0]]["choice"] as ChoiceRow).get_child(1) as Button
		no_games.grab_focus()
		await _press("ui_accept")
	_check(_focus() == setup._next_button, "game window: the last day set goes to Next")

	await _press("ui_left")
	_check(_focus() == setup._back_button, "game window: Left from Next goes to Back")
	await _press("ui_right")
	_check(_focus() == setup._next_button, "game window: Right from Back goes to Next")
	await _press("ui_up")
	var sunday_no := (setup._game_rows["sun"]["choice"] as ChoiceRow).get_child(1)
	_check(_focus() == sunday_no, "game window: Up from Next goes back to Sunday's No games")
	await _press("ui_down")
	_check(_focus() == setup._next_button, "game window: Down from Sunday's No games goes to Next")

	# The jump happens one time only.
	var monday_no := (setup._game_rows["mon"]["choice"] as ChoiceRow).get_child(1) as Button
	var monday_games := (setup._game_rows["mon"]["choice"] as ChoiceRow).get_child(0) as Button
	monday_games.grab_focus()
	await _press("ui_accept")
	monday_no.grab_focus()
	await _press("ui_accept")
	_check(_focus() == monday_no, "game window: a later change does not jump to Next again")
	await _close(setup)


func _test_setup_down_goes_to_back() -> void:
	var setup := SetupScreen.new()
	await _show(setup)
	setup._show_step(8)
	await _frames()
	(setup._bedtimes["sun"] as ValuePicker).grab_focus()
	await _press("ui_down")
	_check(_focus() == setup._back_button, "bedtime: Down from the last row goes to Back while Next is not ready")
	await _press("ui_right")
	_check(_focus() == setup._back_button, "bedtime: Right does not go to a Next that is not ready")
	await _close(setup)


# ---- Copy from USB: the tick list ----

func _test_copy_tick_list() -> void:
	var screen := CopyUsbScreen.new()
	await _show(screen)
	screen.show_sticks([{
		"stick_id": "s1", "label": "BIGDRIVE", "folders": [
			{"key": "films", "name": "Films", "bytes": 1000, "items": [
				{"id": "films:Films/Cars", "title": "Cars", "subtitle": "2006", "bytes": 1000, "on_box": false},
				{"id": "films:Films/Frozen", "title": "Frozen", "subtitle": null, "bytes": 0, "on_box": true},
			]},
			{"key": "music", "name": "Music", "bytes": 500, "items": [
				{"id": "music:Music/Band/Album", "title": "Album", "subtitle": "Band", "bytes": 500, "on_box": false},
			]},
		],
	}])
	await _frames()
	var films_box: TickBox = screen._folders["films"]["box"]
	var music_box: TickBox = screen._folders["music"]["box"]
	var cars_box: TickBox = screen._item_boxes["films:Films/Cars"]
	_check(_focus() == films_box, "tick list: starts on the Films folder")
	_check(screen.copy_button.disabled, "tick list: Copy is off while nothing is ticked")

	await _press("ui_accept")
	_check(screen.ticked_ids() == ["films:Films/Cars"], "tick list: ticking Films ticks its items that are not on the box")
	_check(not screen.copy_button.disabled, "tick list: Copy is on after a tick")

	await _press("ui_right")
	_check(_focus() == screen._folders["films"]["open"], "tick list: Right goes to Open")
	await _press("ui_accept")
	_check(screen.is_open("films"), "tick list: Enter on Open shows the items")
	await _press("ui_left")
	_check(_focus() == films_box, "tick list: Left goes back to the folder")
	await _press("ui_down")
	_check(_focus() == cars_box, "tick list: Down goes to the first item")
	await _press("ui_accept")
	_check(screen.ticked_ids().is_empty() and not films_box.button_pressed, "tick list: unticking the only item unticks the folder")
	await _press("ui_accept")
	_check(films_box.button_pressed, "tick list: ticking it again ticks the folder")

	await _press("ui_down")
	_check(_focus() == music_box, "tick list: Down skips the item that is on the box")
	await _press("ui_accept")
	_check(screen.ticked_ids() == ["films:Films/Cars", "music:Music/Band/Album"], "tick list: both folders ticked")
	await _press("ui_down")
	_check(_focus() == screen.copy_button, "tick list: Down from the last row goes to Copy")
	await _press("ui_up")
	_check(screen.rows.is_ancestor_of(_focus()), "tick list: Up from Copy goes back to the list")
	await _close(screen)


# ---- Music: the menu row ----

func _test_music_menu() -> void:
	var music := MusicScreen.new()
	await _show(music)
	music.show_albums([_album("a1", "First"), _album("a2", "Second"), _album("a3", "Third")])
	await _frames()
	music.first_item().grab_focus()
	await _press("ui_up")
	_check(_focus() == music.menu.first_button(), "music: Up from the first album goes to Albums in the menu")
	for i in 4:
		await _press("ui_right")
	_check(_focus() == music.search_button, "music: Right along the menu reaches Search")
	await _press("ui_right")
	_check(_focus() == music.shuffle_button, "music: then Shuffle all")
	await _press("ui_down")
	_check(_focus() is PosterTile, "music: Down from the menu goes into the albums")

	music.menu.get_child(2).grab_focus()
	await _press("ui_accept")
	_check(music.section == "songs", "music: Enter on Songs shows the songs")
	music.show_songs([_song("s1", "Alpha", "box"), _song("s2", "Beta", "usb")])
	await _frames()
	var first := music.first_item()
	first.grab_focus()
	await _press("ui_right")
	_check(_focus() is Button and (_focus() as Button).text == SongRow.ADD, "music: Right on a box song goes to +")
	await _press("ui_down")
	_check(_focus() is Button and (_focus() as Button).text != SongRow.ADD, "music: a USB song has no +")
	first.grab_focus()
	await _press("ui_up")
	_check(music.menu.is_ancestor_of(_focus()), "music: Up from the first song goes to the menu")
	await _close(music)


func _test_music_screens_open() -> void:
	var playlist := PlaylistScreen.new("p1")
	await _show(playlist)
	playlist.show_playlist({"id": "p1", "name": "Car songs", "can_change": true, "songs": [_song("s1", "Alpha", "box")]})
	await _frames()
	_check(_focus() is Button and (_focus() as Button).text == "Play", "playlist: starts on Play")
	await _press("ui_down")
	await _press("ui_right")
	_check(_focus() is Button and (_focus() as Button).text == SongRow.REMOVE, "playlist: a song the kid may change has −")
	playlist._delete_button.grab_focus()
	await _press("ui_accept")
	_check(playlist._delete_button.text == PlaylistScreen.CONFIRM_TEXT, "playlist: the first Delete asks again")
	await _close(playlist)

	var search := SearchScreen.new()
	await _show(search)
	search.show_results([
		{"kind": "artist", "title": "Band", "subtitle": "1 album", "art_url": null, "artist": "Band"},
		{"kind": "song", "title": "Alpha", "subtitle": "Band", "art_url": null, "song": _song("s1", "Alpha", "box")},
	])
	await _frames()
	_check(search.results.get_child_count() == 2, "search: one list of results")
	search.keyboard.first_button().grab_focus()
	await _press("ui_accept")
	_check(search.keyboard.text == "1", "search: the keyboard types")
	await _close(search)

	var naming := NameScreen.new("Name your playlist", "x".repeat(29))
	await _show(naming)
	naming.keyboard._press("a")
	naming.keyboard._press("b")
	_check(naming.keyboard.text.length() == NameScreen.MAX_LENGTH, "name: stops at 30 letters")
	await _close(naming)

	var progress := CopyProgressScreen.new()
	await _show(progress)
	progress.show_progress({"state": "copying", "job_id": 1, "items_total": 4, "items_done": 1, "bytes_total": 100, "bytes_done": 25,
		"current": "Cars", "skipped": [], "errors": [], "message": null})
	_check(progress._bar.value == 0.25 and not progress._stop_button.visible, "progress: the bar, and no Stop outside parent mode")
	progress.show_progress({"state": "stopped", "job_id": 1, "items_total": 4, "items_done": 1, "bytes_total": 100, "bytes_done": 25,
		"current": null, "skipped": [], "errors": [], "message": "USB removed. Copied 1 of 4. Plug it in again to finish."})
	_check(progress._back_button.text == "Done" and progress._status.text.begins_with("USB removed"), "progress: the end message")
	await _close(progress)

	var usb_item := ItemActionsScreen.new("Cars", "u1", func() -> void: pass)
	await _show(usb_item)
	_check(_focus() == usb_item.play_button, "USB item: starts on Play")
	await _press("ui_right")
	_check(_focus() == usb_item.copy_button, "USB item: Right goes to Copy to the box")
	await _close(usb_item)

	for screen in [AddToPlaylistScreen.new(_song("s1", "Alpha", "box")), ArtistScreen.new("Band"), HomeScreen.new()]:
		await _show(screen)
		_check(screen.is_inside_tree(), "%s opens" % screen.get_script().get_global_name())
		await _close(screen)


# ---- Helpers ----

static func _album(id: String, title: String) -> Dictionary:
	return {"id": id, "title": title, "artist": "Band", "art_url": null, "source": "box", "hidden": false}


static func _song(id: String, title: String, source: String) -> Dictionary:
	return {"id": id, "title": title, "artist": "Band", "album": "Album", "album_id": "a1", "path": "/x.mp3",
		"art_url": null, "source": source, "stick_label": null, "hidden": false}


# ---- Controllers: A presses, B and Back/Select go back (any controller) ----

func _test_controller_buttons() -> void:
	preload("res://scripts/main.gd").add_controller_buttons()
	for device in [0, 3]:
		_check(_joy_event(JOY_BUTTON_A, device).is_action_pressed("ui_accept"), "controller %d: A is ui_accept" % device)
		_check(_joy_event(JOY_BUTTON_B, device).is_action_pressed("ui_cancel"), "controller %d: B is ui_cancel" % device)
		_check(_joy_event(JOY_BUTTON_BACK, device).is_action_pressed("ui_cancel"), "controller %d: Back is ui_cancel" % device)
	_check(not _joy_event(JOY_BUTTON_X, 0).is_action_pressed("ui_accept"), "controller: X is not ui_accept")

	var button := Button.new()
	button.text = "Press me"
	_layer.add_child(button)
	var presses := [0]
	button.pressed.connect(func() -> void: presses[0] += 1)
	button.grab_focus()
	await _frames()
	get_viewport().push_input(_joy_event(JOY_BUTTON_A, 0))
	get_viewport().push_input(_joy_event(JOY_BUTTON_A, 0, false))
	await _frames()
	_check(presses[0] == 1, "controller: A presses the focused button")
	button.queue_free()
	await _frames()


func _test_copy_everything_and_drive_check() -> void:
	var screen := CopyUsbScreen.new()
	await _show(screen)
	screen.show_drive_checks([
		{"drive": {"id": "s1", "label": "Untitled", "mounted": true, "problem": null}, "games_without_core": 1, "hidden": 2,
		 "report": {"videos": 4, "groups": 3, "albums": 3, "songs": 351, "games": 1, "other_files": {".xlsx": 1, ".pdf": 2},
			"skipped_folders": 2, "unreadable": []}},
		{"drive": {"id": "s2", "label": "Mac HD", "mounted": false, "problem": "The box cannot read hfsplus drives. Use FAT32, exFAT, NTFS or ext4."},
		 "games_without_core": 0, "hidden": 0, "report": null},
	])
	_check(screen._check.text == "Mac HD: The box cannot read hfsplus drives. Use FAT32, exFAT, NTFS or ext4.", "drive check: a drive the box cannot read says why")
	screen.show_sticks([{
		"stick_id": "s1", "label": "Untitled", "folders": [
			{"key": "videos", "name": "Videos", "bytes": 300, "items": [
				{"id": "videos:a", "title": "Nature", "subtitle": "2 videos", "bytes": 200, "on_box": false},
				{"id": "videos:b", "title": "Frozen", "subtitle": null, "bytes": 0, "on_box": true},
				{"id": "videos:c", "title": "Lesson", "subtitle": null, "bytes": 100, "on_box": false},
			]},
			{"key": "music", "name": "Albums", "bytes": 50, "items": [
				{"id": "music:d", "title": "Unknown Album", "subtitle": "Nick Lowe", "bytes": 50, "on_box": false},
			]},
		],
	}])
	await _frames()
	_check(screen._check.text.ends_with("Found 4 videos, 3 groups, 3 albums (351 songs), 1 game.  Skipped: 3 other files, 1 game with no emulator, 2 hidden."),
		"drive check: found and skipped for the drive (got %s)" % screen._check.text)
	_check(not screen.copy_all_button.disabled, "copy everything: on when there is something new")
	screen.copy_everything()
	_check(screen.ticked_ids() == ["videos:a", "videos:c", "music:d"], "copy everything: ticks every item that is not on the box")
	await _frames()

	screen.show_sticks([{"stick_id": "s3", "label": "Empty", "folders": []}])
	await _frames()
	_check(screen.copy_all_button.disabled, "copy everything: off when there is nothing new")
	await _close(screen)


# ---- Settings (DESIGN_CORRECTIONS_2.md, part 7) ----

func _test_home_settings_button() -> void:
	var home := HomeScreen.new()
	await _show(home)
	_check(home._settings_button.visible, "home: Settings shows without parent mode")
	var opened: Array = []
	home.open_screen.connect(func(screen: Screen) -> void: opened.append(screen))
	home._settings_button.grab_focus()
	await _press("ui_accept")
	_check(opened.size() == 1 and opened[0] is SettingsScreen, "home: Settings opens the Settings screen")
	for screen in opened:
		screen.free()
	await _close(home)


func _test_settings_update_asks_first() -> void:
	var settings := SettingsScreen.new()
	await _show(settings)
	_check(_focus() == settings._back_button, "settings: starts on Back")
	var api_script: GDScript = load("res://scripts/api.gd")
	settings._show(api_script.Reply.new(true, 200, {
		"installed": "v0.1.0", "latest": "v0.2.0", "available": true, "running": false,
		"check_error": null, "last_result": null, "log": []}))
	await _frames()
	_check(settings._update_button.visible and settings._update_button.text == "Update to v0.2.0", "settings: shows Update to the newest release")

	settings._update_button.grab_focus()
	await _press("ui_accept")
	_check(settings._confirm_row.visible and _focus() == settings._confirm_no, "settings: Update asks first, with No focused")
	settings.go_back()
	await _frames()
	_check(not settings._confirm_row.visible and _focus() == settings._update_button, "settings: Back on the question means No")

	# Down goes through the buttons, then scrolls the text below the last one (About); Up goes back.
	var scroll := settings.key_scroll
	scroll.scroll_vertical = 0
	await _frames()
	var bar := scroll.get_v_scroll_bar()
	_check(bar.max_value > bar.page, "settings: the screen is taller than the TV (the test needs a scroll)")
	for i in 16:
		await _press("ui_down")
	_check(scroll.scroll_vertical >= int(bar.max_value - bar.page), "settings: Down scrolls to the bottom")
	_check(_focus() == settings._lookup_button, "settings: the last button is Look up now")
	for i in 16:
		await _press("ui_up")
	_check(scroll.scroll_vertical == 0, "settings: Up scrolls back to the top")
	await _close(settings)


# ---- Videos and groups (DESIGN_CORRECTIONS_2.md, part 2) ----

func _test_videos_tiles() -> void:
	var videos := VideosScreen.new()
	await _show(videos)
	var group_tile := videos._tile({"kind": "group", "id": "g1", "title": "Bluey", "art_url": null, "video_count": 3, "source": "box", "hidden": false})
	var video_tile := videos._tile({"kind": "video", "id": "v1", "title": "Frozen", "year": 2013, "art_url": null, "seconds": 60.0, "path": "/x.mkv", "source": "usb", "hidden": false})
	videos._grid.add_child(group_tile)
	videos._grid.add_child(video_tile)
	var opened: Array = []
	videos.open_screen.connect(func(screen: Screen) -> void: opened.append(screen))
	group_tile.grab_focus()
	await _press("ui_accept")
	_check(opened.size() == 1 and opened[0] is GroupScreen and opened[0]._group_id == "g1", "videos: a group tile opens the group")
	for screen in opened:
		screen.free()
	await _close(videos)


static func _sample_group(resume: int) -> Dictionary:
	return {
		"id": "g1", "title": "Fargo (2014) Season 5", "art_url": null, "hidden": false, "source": "usb", "stick_label": "Untitled",
		"resume_index": resume,
		"videos": [
			{"id": "e1", "title": "The Tragedy of the Commons", "path": "/1.mkv", "seconds": 60.0, "section": "", "code": "S5 E1"},
			{"id": "e2", "title": "Trials and Tribulations", "path": "/2.mkv", "seconds": 60.0, "section": "", "code": "S5 E2"},
			{"id": "e3", "title": "Making of", "path": "/3.mkv", "seconds": null, "section": "Extras", "code": null},
		],
	}


func _test_group_screen() -> void:
	var group := GroupScreen.new("g1")
	await _show(group)
	group.show_group(_sample_group(0))
	await _frames()
	_check(_focus() == group._play_button and group._play_button.text == "Play", "group: starts on Play")
	var rows: Array[String] = []
	for child in group._videos.get_children():
		rows.append(child.text)
	_check(rows == ["Play", "S5 E1  ·  The Tragedy of the Commons", "S5 E2  ·  Trials and Tribulations", "Extras", "Making of"],
		"group: videos in order, with the section heading (got %s)" % [rows])
	await _press("ui_down")
	_check(_focus() is Button and _focus().get_meta("video_index", -1) == 0, "group: Down goes to the first video")

	group.show_group(_sample_group(1))
	await _frames()
	_check(group._play_button.text == "Play: S5 E2  ·  Trials and Tribulations", "group: Play names the video it resumes at")
	_check((group._videos.get_child(1) as Button).text == "Play from the start", "group: Play from the start is there after a resume")

	# A video that played to its end moves the resume point on; a stopped one does not.
	group._on_video_end(false, 1)
	_check(group._group["resume_index"] == 1, "group: a stopped video does not move on")
	group._on_video_end(true, 2)
	await _frames()
	_check(group._group["resume_index"] == 0, "group: after the last video, Play starts from the beginning again")
	await _close(group)


# ---- Posters and info (DESIGN_CORRECTIONS_2.md, part 4) ----

func _test_posters_settings() -> void:
	var settings := SettingsScreen.new()
	await _show(settings)
	settings.show_posters({
		"accounts": [
			{"key": "tmdb", "name": "TMDB", "used_for": "Posters and details for videos and groups", "state": "not_working", "reason": "The key or password is wrong."},
			{"key": "musicbrainz", "name": "MusicBrainz", "used_for": "Album covers", "state": "not_needed", "reason": null},
		],
		"done": 3, "waiting": 0, "not_found": 2, "failed": 1, "no_account": 4, "last_error": "Home Movie: No internet, or the site cannot be reached.",
	})
	await _frames()
	var rows: Array[String] = []
	for child in settings._accounts.get_children():
		rows.append(child.text)
	_check(rows == ["TMDB  ·  Posters and details for videos and groups  ·  Not working: The key or password is wrong.",
		"MusicBrainz  ·  Album covers  ·  No key needed"], "posters: each source and its state (got %s)" % [rows])
	_check(settings._posters_status.text == "3 have posters and info, 4 wait for a TMDB key, 2 not found, 1 failed.\nLast problem: Home Movie: No internet, or the site cannot be reached.",
		"posters: the counts and the last problem (got %s)" % settings._posters_status.text)
	settings._lookup_button.grab_focus()
	await _press("ui_accept")
	_check(settings._lookup_confirm.visible and _focus() == settings._lookup_no, "posters: Look up now asks first, with No focused")
	settings.go_back()
	await _frames()
	_check(not settings._lookup_confirm.visible and _focus() == settings._lookup_button, "posters: Back on the question means No")

	var opened: Array = []
	settings.open_screen.connect(func(screen: Screen) -> void: opened.append(screen))
	settings._enter_screenscraper()
	_check(opened.size() == 1 and opened[0] is TextEntryScreen and opened[0]._title == "ScreenScraper user name", "posters: ScreenScraper asks for the user name first")
	opened[0].entered.emit("me")
	await _frames()
	_check(opened.size() == 2 and opened[1]._title == "ScreenScraper password" and opened[1]._secret, "posters: then the password, hidden")
	for screen in opened:
		screen.free()
	await _close(settings)


func _test_match_screen() -> void:
	var screen := MatchScreen.new("g1", "Fargo (2014) Season 5")
	await _show(screen)
	screen.show_results([
		{"provider": "tmdb", "provider_id": "tv:9", "title": "Fargo", "year": 2014, "artist": null, "description": "TV series. A crime story.", "preview_url": null},
		{"provider": "tmdb", "provider_id": "movie:2", "title": "Fargo", "year": 1996, "artist": null, "description": null, "preview_url": null},
	])
	await _frames()
	_check(_focus() == screen._results.get_child(0), "match: starts on the first result")
	_check((screen._results.get_child(0) as Button).text == "Fargo (2014)   —   TV series. A crime story.", "match: a result shows its title, year and details")
	await _press("ui_up")
	_check(_focus() == screen._search_button, "match: Up goes to the search, to change it")
	screen.show_results([])
	await _frames()
	_check(screen._message.text == "Nothing found. Change the search." and _focus() == screen._search_button, "match: nothing found goes to the search")
	await _close(screen)


func _joy_event(button: JoyButton, device: int, pressed: bool = true) -> InputEventJoypadButton:
	var event := InputEventJoypadButton.new()
	event.button_index = button
	event.device = device
	event.pressed = pressed
	return event


func _show(screen: Screen) -> void:
	_layer.add_child(screen)
	await _frames()
	var target := screen.default_focus()
	if target != null and target.is_inside_tree():
		target.grab_focus()
	await _frames()


func _close(screen: Screen) -> void:
	screen.queue_free()
	await _frames()


func _frames(count: int = 3) -> void:
	for i in count:
		await get_tree().process_frame


func _press(action: String) -> void:
	var down := InputEventAction.new()
	down.action = action
	down.pressed = true
	get_viewport().push_input(down)
	var up := InputEventAction.new()
	up.action = action
	up.pressed = false
	get_viewport().push_input(up)
	await _frames()


func _focus() -> Control:
	return get_viewport().gui_get_focus_owner()


func _check(passed: bool, description: String) -> void:
	_checks += 1
	if not passed:
		_failures += 1
		var focused := _focus()
		print("FAIL: %s (focus: %s)" % [description, focused.get_path() if focused != null else "none"])
