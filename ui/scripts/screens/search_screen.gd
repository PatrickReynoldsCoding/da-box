class_name SearchScreen
extends Screen
## Find an artist, an album or a song: the keyboard on the left, one list of results on the right.
## The results follow the typing. Done (or Right from the keyboard) goes to the results.

const TYPING_PAUSE_SECONDS := 0.35

var keyboard: OnScreenKeyboard
var results: VBoxContainer
var _message: Label
var _typing_timer: Timer
var _search_number := 0


func _ready() -> void:
	super()
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 24)
	column.add_child(header("Search music", UiTheme.MUSIC))
	var row := HBoxContainer.new()
	row.size_flags_vertical = Control.SIZE_EXPAND_FILL
	row.add_theme_constant_override("separation", 40)
	keyboard = OnScreenKeyboard.new(false, 40)
	keyboard.size_flags_vertical = Control.SIZE_SHRINK_BEGIN
	keyboard.text_changed.connect(func(_text: String) -> void: _typing_timer.start())
	keyboard.submitted.connect(func(_text: String) -> void: _focus_results())
	row.add_child(keyboard)
	var scroll := ScrollContainer.new()
	scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	scroll.follow_focus = true
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	results = VBoxContainer.new()
	results.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	results.add_theme_constant_override("separation", 12)
	scroll.add_child(results)
	row.add_child(scroll)
	column.add_child(row)
	_message = UiTheme.muted_label("Type the name of an artist, an album or a song.", UiTheme.FONT_SIZE)
	column.add_child(_message)
	page_margin(column)
	_typing_timer = Timer.new()
	_typing_timer.one_shot = true
	_typing_timer.wait_time = TYPING_PAUSE_SECONDS
	_typing_timer.timeout.connect(func() -> void: search(keyboard.text))
	add_child(_typing_timer)


func default_focus() -> Control:
	return keyboard.first_button()


func search(text: String) -> void:
	_search_number += 1
	var search_number := _search_number
	if text.strip_edges().is_empty():
		show_results([])
		return
	var reply := await Api.service_get("/box/music/search?q=" + text.uri_encode())
	if search_number != _search_number or not is_inside_tree():
		return
	if not reply.ok:
		_message.text = "The search did not work. Try again soon."
		return
	show_results(reply.data)
	_message.text = "Nothing found. Try fewer letters." if reply.data.is_empty() else ""


func show_results(hits: Array) -> void:
	for child in results.get_children():
		results.remove_child(child)
		child.queue_free()
	for hit in hits:
		match hit["kind"]:
			"artist":
				results.add_child(_hit_button("Artist  ·  %s" % hit["title"], func() -> void: open_screen.emit(ArtistScreen.new(hit["artist"]))))
			"album":
				results.add_child(_hit_button("Album  ·  %s  —  %s" % [hit["title"], hit["subtitle"]], func() -> void: open_screen.emit(AlbumScreen.new(hit["album_id"]))))
			"song":
				var song: Dictionary = hit["song"]
				var song_row := SongRow.new(song, SongRow.ADD if SongRow.can_add(song) else "")
				song_row.play_pressed.connect(_play.bind(song))
				song_row.side_pressed.connect(func() -> void: open_screen.emit(AddToPlaylistScreen.new(song)))
				results.add_child(song_row)


func _hit_button(text: String, action: Callable) -> Button:
	var button := Button.new()
	button.text = text
	button.alignment = HORIZONTAL_ALIGNMENT_LEFT
	button.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	button.clip_text = true
	button.custom_minimum_size.y = 84
	button.add_theme_stylebox_override("normal", UiTheme.rounded_box(Color(1, 1, 1, 0.08), 20))
	button.pressed.connect(action)
	return button


func _focus_results() -> void:
	var first := MusicScreen._find_focusable(results)
	if first != null:
		first.grab_focus()


func _play(song: Dictionary) -> void:
	if await Api.play_songs([song]):
		open_screen.emit(NowPlayingScreen.new(song.get("art_url")))
	else:
		_message.text = "This song would not play."
