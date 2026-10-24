class_name MusicScreen
extends Screen
## Music: a menu row (Albums, Artists, Songs, Playlists, then Search and Shuffle all)
## and the chosen list under it. "Now playing" shows at the top right while music plays.

const SECTIONS := [["albums", "Albums"], ["artists", "Artists"], ["songs", "Songs"], ["playlists", "Playlists"]]
## Picking a song in the song list plays it and the songs after it, up to this many.
const PLAY_WINDOW := 100

var menu: ChoiceRow
var search_button: Button
var shuffle_button: Button
var section := ""
var _content: VBoxContainer
var _message: Label
var _now_playing: Button
var _load_number := 0


func _ready() -> void:
	super()
	var body := VBoxContainer.new()
	body.add_theme_constant_override("separation", 24)
	var top := header("Music", UiTheme.MUSIC)
	_now_playing = Button.new()
	_now_playing.text = "Now playing"
	_now_playing.visible = false
	_now_playing.size_flags_horizontal = Control.SIZE_EXPAND | Control.SIZE_SHRINK_END
	_now_playing.pressed.connect(func() -> void: open_screen.emit(NowPlayingScreen.new()))
	top.add_child(_now_playing)
	body.add_child(top)

	var menu_row := HBoxContainer.new()
	menu_row.add_theme_constant_override("separation", 24)
	menu = ChoiceRow.new(SECTIONS, 220, 80)
	menu.changed.connect(func(value: Variant) -> void: show_section(value))
	menu_row.add_child(menu)
	search_button = _menu_button("Search", func() -> void: open_screen.emit(SearchScreen.new()))
	menu_row.add_child(search_button)
	shuffle_button = _menu_button("Shuffle all", _shuffle_all)
	menu_row.add_child(shuffle_button)
	body.add_child(menu_row)

	_content = VBoxContainer.new()
	_content.size_flags_vertical = Control.SIZE_EXPAND_FILL
	body.add_child(_content)
	_message = UiTheme.muted_label("")
	body.add_child(_message)
	page_margin(body)
	menu.select("albums")


func default_focus() -> Control:
	if _now_playing.visible:
		return _now_playing
	var first := first_item()
	return first if first != null else menu.first_button()


func on_shown() -> void:
	var reply := await Api.agent_get("/status")
	_now_playing.visible = reply.ok and reply.data.get("kind") == "audio"
	# A playlist may have changed on the screen above.
	if section == "playlists" and is_inside_tree():
		show_section("playlists")


## The first tile or row of the list under the menu.
func first_item() -> Control:
	return _find_focusable(_content)


func show_section(section_name: String) -> void:
	section = section_name
	_message.text = ""
	_load_number += 1
	var load_number := _load_number
	var paths := {
		"albums": "/box/music/albums", "artists": "/box/music/artists",
		"songs": "/box/music/songs", "playlists": "/box/music/playlists",
	}
	var reply := await Api.service_get(paths[section_name])
	if load_number != _load_number or not is_inside_tree():
		return  # Another section was picked meanwhile.
	_clear_content()
	if not reply.ok:
		_message.text = "The music could not load. Try again soon."
		return
	match section_name:
		"albums":
			show_albums(reply.data)
		"artists":
			show_artists(reply.data)
		"songs":
			show_songs(reply.data)
		"playlists":
			show_playlists(reply.data)


func show_albums(albums: Array) -> void:
	_clear_content()
	if albums.is_empty():
		_content.add_child(empty_message("No music yet. Ask a grown-up to add some!"))
		return
	var grid := _add_grid()
	for album in albums:
		var tile := album_tile(album)
		tile.pressed.connect(func() -> void: open_screen.emit(AlbumScreen.new(album["id"])))
		grid.add_child(tile)


func show_artists(artists: Array) -> void:
	_clear_content()
	if artists.is_empty():
		_content.add_child(empty_message("No music yet. Ask a grown-up to add some!"))
		return
	var grid := _add_grid()
	for artist in artists:
		var count := int(artist["album_count"])
		var subtitle := "%d album%s" % [count, "" if count == 1 else "s"]
		var tile := PosterTile.new(artist["name"], subtitle, _text(artist["art_url"]), UiTheme.MUSIC.darkened(0.3), true)
		tile.pressed.connect(func() -> void: open_screen.emit(ArtistScreen.new(artist["name"])))
		grid.add_child(tile)


func show_songs(songs: Array) -> void:
	_clear_content()
	if songs.is_empty():
		_content.add_child(empty_message("No music yet. Ask a grown-up to add some!"))
		return
	var list := _add_list()
	for index in songs.size():
		var song: Dictionary = songs[index]
		var row := SongRow.new(song, SongRow.ADD if SongRow.can_add(song) else "")
		row.play_pressed.connect(func() -> void: _play(songs.slice(index, index + PLAY_WINDOW)))
		row.side_pressed.connect(func() -> void: open_screen.emit(AddToPlaylistScreen.new(song)))
		list.add_child(row)


func show_playlists(playlists: Array) -> void:
	_clear_content()
	var grid := _add_grid()
	var make := PosterTile.new("New playlist", "Make your own", "", UiTheme.GOOD.darkened(0.3), true)
	make.pressed.connect(_make_playlist)
	grid.add_child(make)
	for playlist in playlists:
		var count := int(playlist["song_count"])
		var subtitle := "%d song%s" % [count, "" if count == 1 else "s"]
		var tile := PosterTile.new(playlist["name"], subtitle, _text(playlist["art_url"]), UiTheme.MUSIC.darkened(0.3), true)
		tile.pressed.connect(func() -> void: open_screen.emit(PlaylistScreen.new(playlist["id"])))
		grid.add_child(tile)


static func album_tile(album: Dictionary) -> PosterTile:
	return PosterTile.new(album["title"], album["artist"], _text(album["art_url"]), UiTheme.MUSIC.darkened(0.3), true, PosterTile.badge_text(album))


func _make_playlist() -> void:
	var naming := NameScreen.new("Name your playlist")
	naming.named.connect(func(playlist_name: String) -> void:
		var reply := await Api.service_post("/box/music/playlists", {"name": playlist_name})
		if reply.ok:
			open_screen.emit(PlaylistScreen.new(reply.data["id"]))
		else:
			_message.text = Api.error_text(reply, "The playlist could not be made."))
	open_screen.emit(naming)


func _shuffle_all() -> void:
	var reply := await Api.service_get("/box/music/shuffle")
	if not reply.ok or reply.data.is_empty():
		_message.text = "There is no music on the box to shuffle."
		return
	_play(reply.data)


func _play(songs: Array) -> void:
	if await Api.play_songs(songs):
		open_screen.emit(NowPlayingScreen.new(songs[0].get("art_url")))
	else:
		_message.text = "This music would not play."


func _menu_button(text: String, action: Callable) -> Button:
	var button := Button.new()
	button.text = text
	button.focus_mode = Control.FOCUS_ALL
	button.custom_minimum_size = Vector2(220, 80)
	button.pressed.connect(action)
	return button


func _add_grid() -> GridContainer:
	var parts := scrolling_grid(4)
	_content.add_child(parts[0])
	return parts[1]


func _add_list() -> VBoxContainer:
	var scroll := ScrollContainer.new()
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	scroll.follow_focus = true
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	var list := VBoxContainer.new()
	list.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	list.add_theme_constant_override("separation", 12)
	scroll.add_child(list)
	_content.add_child(scroll)
	return list


func _clear_content() -> void:
	for child in _content.get_children():
		_content.remove_child(child)
		child.queue_free()


static func _find_focusable(node: Node) -> Control:
	for child in node.get_children():
		if child is Control and (child as Control).focus_mode != Control.FOCUS_NONE and (child as Control).visible:
			return child
		var found := _find_focusable(child)
		if found != null:
			return found
	return null


static func _text(value: Variant) -> String:
	return value if value is String else ""
