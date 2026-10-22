class_name HomeScreen
extends Screen
## The four big tiles. TV and Games come in later build phases.

var _tv_tile: BigTile
var _films_tile: BigTile
var _music_tile: BigTile
var _games_tile: BigTile
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
	for tile in [_tv_tile, _films_tile, _music_tile, _games_tile]:
		tile.size_flags_vertical = Control.SIZE_SHRINK_CENTER
		tiles.add_child(tile)
	column.add_child(tiles)

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
	_leave_parent_mode.visible = state.get("parent_mode", false)


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
