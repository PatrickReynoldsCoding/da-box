class_name HomeScreen
extends Screen
## The four big tiles (TV, Films, Music, Games). In parent mode a fifth tile, USB,
## copies from a USB drive. A bar under the tiles shows a copy while it runs.

const TILE_WIDTH := 380.0
const NARROW_TILE_WIDTH := 300.0
## How long Home shows how the last copy ended.
const COPY_RESULT_SECONDS := 600.0

var _tv_tile: BigTile
var _films_tile: BigTile
var _music_tile: BigTile
var _games_tile: BigTile
var _usb_tile: BigTile
var _copy_bar: Button
var _copy_label: Label
var _copy_progress: ProgressBar
var _clock: Label
var _leave_parent_mode: Button


func _ready() -> void:
	super()
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 60)

	var top := HBoxContainer.new()
	var greeting := UiTheme.title_label("What shall we do?")
	greeting.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	top.add_child(greeting)
	_clock = UiTheme.title_label("")
	_clock.add_theme_color_override("font_color", UiTheme.TEXT_MUTED)
	top.add_child(_clock)
	column.add_child(top)

	var tiles := HBoxContainer.new()
	tiles.alignment = BoxContainer.ALIGNMENT_CENTER
	tiles.size_flags_vertical = Control.SIZE_EXPAND_FILL
	tiles.add_theme_constant_override("separation", 48)
	_tv_tile = BigTile.new("TV", Icon.Kind.TV, UiTheme.TV)
	_tv_tile.pressed.connect(func() -> void: open_screen.emit(GuideScreen.new()))
	_films_tile = BigTile.new("Films", Icon.Kind.FILM, UiTheme.FILMS)
	_music_tile = BigTile.new("Music", Icon.Kind.MUSIC, UiTheme.MUSIC)
	_games_tile = BigTile.new("Games", Icon.Kind.GAME, UiTheme.GAMES)
	_films_tile.pressed.connect(func() -> void: open_screen.emit(FilmsScreen.new()))
	_music_tile.pressed.connect(func() -> void: open_screen.emit(MusicScreen.new()))
	_games_tile.pressed.connect(func() -> void: open_screen.emit(GamesScreen.new()))
	_usb_tile = BigTile.new("USB", Icon.Kind.USB, UiTheme.WARNING, "Copy to the box")
	_usb_tile.pressed.connect(func() -> void: open_screen.emit(CopyUsbScreen.new()))
	for tile in [_tv_tile, _films_tile, _music_tile, _games_tile, _usb_tile]:
		tile.size_flags_vertical = Control.SIZE_SHRINK_CENTER
		tiles.add_child(tile)
	column.add_child(tiles)
	column.add_child(_make_copy_bar())

	var bottom := HBoxContainer.new()
	bottom.alignment = BoxContainer.ALIGNMENT_END
	var mascot := Mascot.new()
	bottom.add_child(mascot)
	column.add_child(bottom)

	_leave_parent_mode = Button.new()
	_leave_parent_mode.text = "Leave parent mode"
	_leave_parent_mode.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	_leave_parent_mode.pressed.connect(_on_leave_parent_mode)
	column.add_child(_leave_parent_mode)

	page_margin(column)
	Api.state_changed.connect(_on_state_changed)
	_on_state_changed(Api.state)
	Api.limits_changed.connect(_on_limits_changed)
	_on_limits_changed(Api.limits)
	Api.copy_changed.connect(_on_copy_changed)
	_on_copy_changed(Api.copy_progress)
	_tick_clock()
	var timer := Timer.new()
	timer.wait_time = 1.0
	timer.autostart = true
	timer.timeout.connect(_tick_clock)
	add_child(timer)


func default_focus() -> Control:
	return _films_tile


func go_back() -> void:
	pass


func on_shown() -> void:
	_refresh_music_subtitle()


func _on_limits_changed(limits: Dictionary) -> void:
	if limits.is_empty() or limits.get("unlimited", false):
		for tile in [_tv_tile, _films_tile, _games_tile]:
			tile.set_subtitle("")
		return
	var video_text := "Sleeping" if limits["video_locked"] else "%s left" % Api.minutes_text(limits["video_seconds_left"])
	_tv_tile.set_subtitle(video_text)
	_films_tile.set_subtitle(video_text)
	_games_tile.set_subtitle(limits["games_message"])


func _on_state_changed(state: Dictionary) -> void:
	var parent: bool = state.get("parent_mode", false)
	_leave_parent_mode.visible = parent
	if not parent and _usb_tile.has_focus():
		_games_tile.grab_focus()
	_usb_tile.visible = parent
	for tile in [_tv_tile, _films_tile, _music_tile, _games_tile, _usb_tile]:
		tile.custom_minimum_size.x = NARROW_TILE_WIDTH if parent else TILE_WIDTH
	_copy_bar.focus_mode = Control.FOCUS_ALL if parent else Control.FOCUS_NONE


func _make_copy_bar() -> Button:
	_copy_bar = Button.new()
	_copy_bar.custom_minimum_size = Vector2(900, 110)
	_copy_bar.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	_copy_bar.visible = false
	_copy_bar.pressed.connect(func() -> void: open_screen.emit(CopyProgressScreen.new()))
	var inside := VBoxContainer.new()
	inside.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT, Control.PRESET_MODE_MINSIZE, 18)
	inside.mouse_filter = Control.MOUSE_FILTER_IGNORE
	inside.alignment = BoxContainer.ALIGNMENT_CENTER
	inside.add_theme_constant_override("separation", 8)
	_copy_label = UiTheme.muted_label("")
	_copy_label.autowrap_mode = TextServer.AUTOWRAP_OFF
	_copy_label.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	_copy_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	inside.add_child(_copy_label)
	_copy_progress = ProgressBar.new()
	_copy_progress.show_percentage = false
	_copy_progress.max_value = 1.0
	_copy_progress.custom_minimum_size.y = 16
	inside.add_child(_copy_progress)
	_copy_bar.add_child(inside)
	return _copy_bar


func _on_copy_changed(progress: Dictionary) -> void:
	var state: String = progress.get("state", "idle")
	var since: Variant = progress.get("seconds_since_end")
	var recent := state != "idle" and state != "copying" and since != null and float(since) < COPY_RESULT_SECONDS
	if not (state == "copying" or recent):
		if _copy_bar.has_focus():
			_films_tile.grab_focus()
		_copy_bar.visible = false
		return
	_copy_bar.visible = true
	var total := float(progress.get("bytes_total", 0))
	if state == "copying":
		_copy_progress.visible = true
		_copy_progress.value = float(progress.get("bytes_done", 0)) / total if total > 0 else 0.0
		_copy_label.text = "Copying from USB: %d of %d  ·  %d%%" % [
			progress.get("items_done", 0), progress.get("items_total", 0), roundi(_copy_progress.value * 100)]
	else:
		_copy_progress.visible = false
		var message: Variant = progress.get("message")
		_copy_label.text = message if message is String else ""


func _on_leave_parent_mode() -> void:
	await Api.service_post("/box/parent-mode/leave")
	await Api.refresh_state()
	_films_tile.grab_focus()


func _refresh_music_subtitle() -> void:
	var reply := await Api.agent_get("/status")
	var playing_music: bool = reply.ok and reply.data.get("kind") == "audio"
	if is_instance_valid(_music_tile):
		_music_tile.set_subtitle("Playing now" if playing_music else "")


func _tick_clock() -> void:
	_clock.text = Time.get_time_string_from_system().left(5)
