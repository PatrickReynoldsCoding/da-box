class_name PlaylistScreen
extends Screen
## One playlist: Play, Shuffle, and (for playlists the kid may change) Rename, Delete and "−" on each song.

const DELETE_TEXT := "Delete"
const CONFIRM_TEXT := "Press again to delete"

var _playlist_id: String
var _playlist: Dictionary = {}
var _title: Label
var _actions: HBoxContainer
var _play_button: Button
var _delete_button: Button
var _songs: VBoxContainer
var _message: Label


func _init(playlist_id: String) -> void:
	_playlist_id = playlist_id


func _ready() -> void:
	super()
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 24)
	var top := header("", UiTheme.MUSIC)
	_title = top.get_child(1) as Label
	column.add_child(top)
	_actions = HBoxContainer.new()
	_actions.add_theme_constant_override("separation", 24)
	column.add_child(_actions)
	var scroll := ScrollContainer.new()
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	scroll.follow_focus = true
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	_songs = VBoxContainer.new()
	_songs.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_songs.add_theme_constant_override("separation", 12)
	scroll.add_child(_songs)
	column.add_child(scroll)
	_message = UiTheme.muted_label("", UiTheme.FONT_SIZE)
	column.add_child(_message)
	page_margin(column)
	_load()


func default_focus() -> Control:
	return _play_button


func _load(focus_index: int = -1) -> void:
	var reply := await Api.service_get("/box/music/playlists/" + _playlist_id)
	if not reply.ok:
		_message.text = "This playlist could not load."
		return
	show_playlist(reply.data, focus_index)


func show_playlist(playlist: Dictionary, focus_index: int = -1) -> void:
	_playlist = playlist
	_title.text = playlist["name"]
	for node in [_actions, _songs]:
		for child in node.get_children():
			node.remove_child(child)
			child.queue_free()
	var songs: Array = playlist["songs"]
	var can_change: bool = playlist["can_change"]
	_play_button = _action("Play", func() -> void: _play(songs))
	_actions.add_child(_play_button)
	_actions.add_child(_action("Shuffle", func() -> void: _play(_shuffled(songs))))
	if can_change:
		_actions.add_child(_action("Rename", _rename))
		_delete_button = _action(DELETE_TEXT, _delete)
		_delete_button.focus_exited.connect(func() -> void: _delete_button.text = DELETE_TEXT)
		_actions.add_child(_delete_button)
	if songs.is_empty():
		var hint := "No songs yet. Add songs with \"+\" in Songs, or from Now playing." if can_change else "No songs yet."
		_songs.add_child(empty_message(hint))
	for index in songs.size():
		var row := SongRow.new(songs[index], SongRow.REMOVE if can_change else "", true)
		row.play_pressed.connect(func() -> void: _play(songs, index))
		row.side_pressed.connect(_remove.bind(songs[index]["id"], index))
		_songs.add_child(row)
	# The buttons were rebuilt: focus the next song after a removal, else Play.
	_focus_row.call_deferred(mini(focus_index, songs.size() - 1))


func _action(text: String, action: Callable) -> Button:
	var button := Button.new()
	button.text = text
	button.custom_minimum_size = Vector2(220, 84)
	button.pressed.connect(action)
	return button


func _focus_row(index: int) -> void:
	if index < 0:
		_play_button.grab_focus()
		return
	var row := _songs.get_child(index) as SongRow
	if row != null and row.side_button != null:
		row.side_button.grab_focus()


static func _shuffled(songs: Array) -> Array:
	var order := songs.duplicate()
	order.shuffle()
	return order


func _play(songs: Array, start_index: int = 0) -> void:
	if songs.is_empty():
		return
	if await Api.play_songs(songs, start_index):
		open_screen.emit(NowPlayingScreen.new(songs[start_index].get("art_url")))
	else:
		_message.text = "This music would not play."


func _remove(song_id: String, index: int) -> void:
	var reply := await Api.service_delete("/box/music/playlists/%s/songs/%s" % [_playlist_id, song_id])
	if reply.ok:
		show_playlist(reply.data, index)
	else:
		_message.text = Api.error_text(reply, "The song could not be taken off.")


func _rename() -> void:
	var naming := NameScreen.new("Rename the playlist", _playlist.get("name", ""))
	naming.named.connect(func(playlist_name: String) -> void:
		var reply := await Api.service_put("/box/music/playlists/" + _playlist_id, {"name": playlist_name})
		if reply.ok:
			show_playlist(reply.data)
		else:
			_message.text = Api.error_text(reply, "The playlist could not be renamed."))
	open_screen.emit(naming)


func _delete() -> void:
	# No dialog boxes on the TV: the first press asks, the second deletes.
	if _delete_button.text != CONFIRM_TEXT:
		_delete_button.text = CONFIRM_TEXT
		return
	var reply := await Api.service_delete("/box/music/playlists/" + _playlist_id)
	if reply.ok:
		close_screen.emit()
	else:
		_message.text = Api.error_text(reply, "The playlist could not be deleted.")
