class_name ArtistScreen
extends Screen
## The albums of one artist.

var _artist: String
var _grid: GridContainer
var _body: VBoxContainer
var _message: Label


func _init(artist: String) -> void:
	_artist = artist


func _ready() -> void:
	super()
	_body = VBoxContainer.new()
	_body.add_theme_constant_override("separation", 30)
	_body.add_child(header(_artist, UiTheme.MUSIC))
	var parts := scrolling_grid(4)
	_body.add_child(parts[0])
	_grid = parts[1]
	_message = UiTheme.muted_label("")
	_body.add_child(_message)
	page_margin(_body)
	_load()


func default_focus() -> Control:
	return _grid.get_child(0) as Control if _grid.get_child_count() > 0 else null


func _load() -> void:
	var reply := await Api.service_get("/box/music/albums?artist=" + _artist.uri_encode())
	if not reply.ok:
		_message.text = "The albums could not load."
		return
	for album in reply.data:
		var tile := MusicScreen.album_tile(album)
		tile.pressed.connect(func() -> void: open_screen.emit(AlbumScreen.new(album["id"])))
		_grid.add_child(tile)
	var target := default_focus()
	if target != null:
		target.grab_focus()
