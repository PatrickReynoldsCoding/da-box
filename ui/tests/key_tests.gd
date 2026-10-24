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
	await _test_music_menu()
	await _test_music_screens_open()
	await _test_controller_buttons()
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

	var usb_item := UsbItemScreen.new("Cars", "u1", func() -> void: pass)
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
