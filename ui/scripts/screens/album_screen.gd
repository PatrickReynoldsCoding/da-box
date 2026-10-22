class_name AlbumScreen
extends Screen
## One album: cover on the left, "Play all" and the tracks on the right.

var _album_id: String
var _album: Dictionary = {}
var _cover: TextureRect
var _title: Label
var _artist: Label
var _tracks: VBoxContainer
var _message: Label


func _init(album_id: String) -> void:
	_album_id = album_id


func _ready() -> void:
	super()
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 80)

	var left := VBoxContainer.new()
	left.add_theme_constant_override("separation", 20)
	_cover = TextureRect.new()
	_cover.custom_minimum_size = Vector2(560, 560)
	_cover.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	_cover.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_COVERED
	left.add_child(_cover)
	_title = UiTheme.title_label("")
	_title.custom_minimum_size.x = 560
	_title.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	left.add_child(_title)
	_artist = UiTheme.muted_label("", UiTheme.FONT_SIZE)
	left.add_child(_artist)
	row.add_child(left)

	var scroll := ScrollContainer.new()
	scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	scroll.follow_focus = true
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	_tracks = VBoxContainer.new()
	_tracks.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_tracks.add_theme_constant_override("separation", 16)
	scroll.add_child(_tracks)
	row.add_child(scroll)

	var column := VBoxContainer.new()
	column.add_child(row)
	row.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_message = UiTheme.muted_label("")
	column.add_child(_message)
	page_margin(column)
	_load()


func default_focus() -> Control:
	return _tracks.get_child(0) as Control if _tracks.get_child_count() > 0 else null


func _load() -> void:
	var reply := await Api.service_get("/box/music/albums/" + _album_id)
	if not reply.ok:
		_message.text = "This album could not load."
		return
	_album = reply.data
	_title.text = _album["title"]
	_artist.text = _album["artist"]
	if _album["art_url"] is String:
		_cover.texture = await Api.texture(_album["art_url"])

	_tracks.add_child(_track_button("Play all", 0, UiTheme.MUSIC))
	var number := 1
	for track in _album["tracks"]:
		_tracks.add_child(_track_button("%d.  %s" % [number, track["title"]], number - 1, Color(1, 1, 1, 0.08)))
		number += 1
	default_focus().grab_focus()


func _track_button(text: String, start_index: int, colour: Color) -> Button:
	var button := Button.new()
	button.text = text
	button.alignment = HORIZONTAL_ALIGNMENT_LEFT
	button.custom_minimum_size.y = 90
	button.add_theme_stylebox_override("normal", UiTheme.rounded_box(colour, 20))
	button.pressed.connect(_play.bind(start_index))
	return button


func _play(start_index: int) -> void:
	var items := []
	for track in _album["tracks"]:
		items.append({"path": track["path"], "title": track["title"], "artist": track["artist"]})
	var reply := await Api.agent_post("/play", {"kind": "audio", "items": items, "start_index": start_index})
	if reply.ok:
		open_screen.emit(NowPlayingScreen.new(_album.get("art_url", "")))
	else:
		_message.text = "This music would not play."
