class_name FilmsScreen
extends Screen
## Grid of film posters. Pick one to play it.

var _grid: GridContainer
var _body: VBoxContainer
var _message: Label


func _ready() -> void:
	super()
	_body = VBoxContainer.new()
	_body.add_theme_constant_override("separation", 30)
	_body.add_child(header("Films", UiTheme.FILMS))
	var parts := scrolling_grid(5)
	_body.add_child(parts[0])
	_grid = parts[1]
	_message = UiTheme.muted_label("")
	_body.add_child(_message)
	page_margin(_body)
	_load()


func default_focus() -> Control:
	return _grid.get_child(0) as Control if _grid.get_child_count() > 0 else null


func _load() -> void:
	var reply := await Api.service_get("/box/films")
	if not reply.ok:
		_message.text = "The films could not load. Try again soon."
		return
	var films: Array = reply.data
	if films.is_empty():
		_body.add_child(empty_message("No films yet. Ask a grown-up to add some!"))
		return
	for film in films:
		var year_text := str(int(film["year"])) if film["year"] != null else ""
		var badge := PosterTile.badge_text(film)
		var tile := PosterTile.new(film["title"], year_text, _text_or_empty(film["art_url"]), UiTheme.FILMS.darkened(0.3), false, badge)
		tile.set_unavailable(not Api.video_fits(_film_seconds(film)))
		tile.pressed.connect(_play.bind(film))
		_grid.add_child(tile)
	default_focus().grab_focus()


## Films with an unknown length count as 90 minutes, to be safe.
static func _film_seconds(film: Dictionary) -> float:
	return film["seconds"] if film.get("seconds") != null else 90.0 * 60.0


func _play(film: Dictionary) -> void:
	var refusal := await Api.approve_video(_film_seconds(film))
	if not refusal.is_empty():
		_message.text = refusal
		return
	var reply := await Api.agent_post("/play", {
		"kind": "video",
		"items": [{"path": film["path"], "title": film["title"]}],
	})
	if reply.ok:
		open_screen.emit(VideoScreen.new(film["title"]))
	else:
		_message.text = "That film would not play."


static func _text_or_empty(value: Variant) -> String:
	return value if value is String else ""
