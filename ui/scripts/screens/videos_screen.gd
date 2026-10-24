class_name VideosScreen
extends Screen
## Grid of videos and groups together (DESIGN_CORRECTIONS_2.md, part 2). A video plays;
## a group opens its list of videos.

## Videos with an unknown length count as 90 minutes, to be safe.
const UNKNOWN_SECONDS := 90.0 * 60.0

var _grid: GridContainer
var _body: VBoxContainer
var _message: Label


func _ready() -> void:
	super()
	_body = VBoxContainer.new()
	_body.add_theme_constant_override("separation", 30)
	_body.add_child(header("Videos", UiTheme.FILMS))
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
	var reply := await Api.service_get("/box/videos")
	if not reply.ok:
		_message.text = "The videos could not load. Try again soon."
		return
	var tiles: Array = reply.data
	if tiles.is_empty():
		_body.add_child(empty_message("No videos yet. Ask a grown-up to add some!"))
		return
	for item in tiles:
		_grid.add_child(_tile(item))
	default_focus().grab_focus()


func _tile(item: Dictionary) -> PosterTile:
	var badge := PosterTile.badge_text(item)
	var art := _text_or_empty(item["art_url"])
	if item["kind"] == "group":
		var count := int(item["video_count"])
		var tile := PosterTile.new(item["title"], "%d videos" % count, art, UiTheme.FILMS.darkened(0.45), false, badge)
		tile.pressed.connect(func() -> void: open_screen.emit(GroupScreen.new(item["id"])))
		return tile
	var year_text := str(int(item["year"])) if item["year"] != null else ""
	var tile := PosterTile.new(item["title"], year_text, art, UiTheme.FILMS.darkened(0.3), false, badge)
	tile.set_unavailable(not Api.video_fits(video_seconds(item)))
	tile.pressed.connect(_pick.bind(item))
	return tile


static func video_seconds(video: Dictionary) -> float:
	return video["seconds"] if video.get("seconds") != null else UNKNOWN_SECONDS


## In parent mode a video also has "Posters and info", and a USB video "Copy to the box".
func _pick(video: Dictionary) -> void:
	if Api.parent_mode():
		open_screen.emit(ItemActionsScreen.new(video["title"], video["id"], _play.bind(video), video.get("source") == "usb", true))
	else:
		_play(video)


func _play(video: Dictionary) -> void:
	var refusal := await Api.approve_video(video_seconds(video))
	if not refusal.is_empty():
		_message.text = refusal
		return
	var reply := await Api.agent_post("/play", {
		"kind": "video",
		"items": [{"path": video["path"], "title": video["title"]}],
	})
	if reply.ok:
		open_screen.emit(VideoScreen.new(video["title"]))
	else:
		_message.text = "That video would not play."


static func _text_or_empty(value: Variant) -> String:
	return value if value is String else ""
