class_name MusicScreen
extends Screen
## Grid of album covers, with a "Now playing" tile first while music plays.

var _grid: GridContainer
var _body: VBoxContainer
var _message: Label
var _now_playing: Button


func _ready() -> void:
	super()
	_body = VBoxContainer.new()
	_body.add_theme_constant_override("separation", 30)
	var top := header("Music", UiTheme.MUSIC)
	_now_playing = Button.new()
	_now_playing.text = "Now playing"
	_now_playing.visible = false
	_now_playing.size_flags_horizontal = Control.SIZE_EXPAND | Control.SIZE_SHRINK_END
	_now_playing.pressed.connect(func() -> void: open_screen.emit(NowPlayingScreen.new()))
	top.add_child(_now_playing)
	_body.add_child(top)
	var parts := scrolling_grid(4)
	_body.add_child(parts[0])
	_grid = parts[1]
	_message = UiTheme.muted_label("")
	_body.add_child(_message)
	page_margin(_body)
	_load()


func default_focus() -> Control:
	if _now_playing.visible:
		return _now_playing
	return _grid.get_child(0) as Control if _grid.get_child_count() > 0 else null


func on_shown() -> void:
	var reply := await Api.agent_get("/status")
	_now_playing.visible = reply.ok and reply.data.get("kind") == "audio"


func _load() -> void:
	var reply := await Api.service_get("/box/music/albums")
	if not reply.ok:
		_message.text = "The music could not load. Try again soon."
		return
	var albums: Array = reply.data
	if albums.is_empty():
		_body.add_child(empty_message("No music yet. Ask a grown-up to add some!"))
		return
	for album in albums:
		var badge := PosterTile.badge_text(album)
		var art_url: String = album["art_url"] if album["art_url"] is String else ""
		var tile := PosterTile.new(album["title"], album["artist"], art_url, UiTheme.MUSIC.darkened(0.3), true, badge)
		tile.pressed.connect(func() -> void: open_screen.emit(AlbumScreen.new(album["id"])))
		_grid.add_child(tile)
	var target := default_focus()
	if target != null:
		target.grab_focus()
