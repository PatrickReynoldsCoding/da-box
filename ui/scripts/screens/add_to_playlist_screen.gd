class_name AddToPlaylistScreen
extends Screen
## Puts one song on a playlist: pick a playlist, or make a new one.

var _song: Dictionary
var _list: VBoxContainer
var _message: Label


func _init(song: Dictionary) -> void:
	_song = song


func _ready() -> void:
	super()
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 24)
	column.add_child(header("Add to a playlist", UiTheme.MUSIC))
	column.add_child(UiTheme.muted_label("%s  —  %s" % [_song["title"], _song["artist"]], UiTheme.FONT_SIZE))
	var scroll := ScrollContainer.new()
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	scroll.follow_focus = true
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	_list = VBoxContainer.new()
	_list.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_list.add_theme_constant_override("separation", 12)
	scroll.add_child(_list)
	column.add_child(scroll)
	_message = UiTheme.muted_label("", UiTheme.FONT_SIZE)
	column.add_child(_message)
	page_margin(column)
	_list.add_child(_row("New playlist", _make_playlist, UiTheme.GOOD.darkened(0.3)))
	_load()


func default_focus() -> Control:
	return _list.get_child(0) as Control


func _load() -> void:
	var reply := await Api.service_get("/box/music/playlists")
	if not reply.ok:
		_message.text = "The playlists could not load."
		return
	for playlist in reply.data:
		# A kid can add only to playlists made on the box.
		if playlist["can_change"]:
			_list.add_child(_row(playlist["name"], _add.bind(playlist["id"], playlist["name"])))


func _row(text: String, action: Callable, colour: Color = Color(1, 1, 1, 0.08)) -> Button:
	var button := Button.new()
	button.text = text
	button.alignment = HORIZONTAL_ALIGNMENT_LEFT
	button.custom_minimum_size.y = 90
	button.add_theme_stylebox_override("normal", UiTheme.rounded_box(colour, 20))
	button.pressed.connect(action)
	return button


func _add(playlist_id: String, playlist_name: String) -> void:
	var reply := await Api.service_post("/box/music/playlists/%s/songs" % playlist_id, {"song_id": _song["id"]})
	if not reply.ok:
		_message.text = Api.error_text(reply, "The song could not be added.")
		return
	_message.text = "Added to %s!" % playlist_name
	await get_tree().create_timer(0.8).timeout
	close_screen.emit()


func _make_playlist() -> void:
	var naming := NameScreen.new("Name your playlist")
	naming.named.connect(func(playlist_name: String) -> void:
		var reply := await Api.service_post("/box/music/playlists", {"name": playlist_name})
		if reply.ok:
			_add(reply.data["id"], playlist_name)
		else:
			_message.text = Api.error_text(reply, "The playlist could not be made."))
	open_screen.emit(naming)
