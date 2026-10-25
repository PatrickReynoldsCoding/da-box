class_name GamesScreen
extends Screen
## Grid of games. Closed outside the game window (the tiles are faded and a line says when games open).

var _grid: GridContainer
var _body: VBoxContainer
var _message: Label


func _ready() -> void:
	super()
	_body = VBoxContainer.new()
	_body.add_theme_constant_override("separation", 30)
	_body.add_child(header("Games", UiTheme.GAMES))
	_message = UiTheme.muted_label("", UiTheme.FONT_SIZE)
	_body.add_child(_message)
	var parts := scrolling_grid(5)
	_body.add_child(parts[0])
	_grid = parts[1]
	page_margin(_body)
	_load()


func default_focus() -> Control:
	return _grid.get_child(0) as Control if _grid.get_child_count() > 0 else null


func _games_open() -> bool:
	return Api.limits.get("unlimited", false) or Api.limits.get("games_open", false)


func _load() -> void:
	await Api.refresh_limits()
	var reply := await Api.service_get("/box/games")
	if not reply.ok:
		_message.text = "The games could not load. Try again soon."
		return
	var games: Array = reply.data
	if games.is_empty():
		_body.add_child(empty_message("No games yet. Ask a grown-up to add some!"))
		return
	var open := _games_open()
	_message.text = "" if Api.limits.get("unlimited", false) else String(Api.limits.get("games_message", ""))
	for game in games:
		var art_url: String = game["art_url"] if game["art_url"] is String else ""
		var tile := PosterTile.new(game["title"], game["system_name"], art_url, UiTheme.GAMES.darkened(0.3), true, PosterTile.badge_text(game), Icon.Kind.GAME)
		tile.set_unavailable(not open)
		tile.pressed.connect(_pick.bind(game))
		_grid.add_child(tile)
	default_focus().grab_focus()


## In parent mode a USB game can also be copied to the box. Its saves stay (they follow the file's content).
func _pick(game: Dictionary) -> void:
	if Api.parent_mode() and game.get("source") == "usb":
		open_screen.emit(ItemActionsScreen.new(game["title"], game["id"], _play.bind(game)))
	else:
		_play(game)


func _play(game: Dictionary) -> void:
	var decision := await Api.service_post("/box/limits/game")
	if not decision.ok or not decision.data["allowed"]:
		_message.text = decision.data["reason"] if decision.ok else "The box could not check game time."
		return
	var reply := await Api.agent_post("/play-game", {
		"path": game["path"], "core": game["core"], "save_key": game["save_key"], "title": game["title"],
	})
	if reply.ok:
		open_screen.emit(GameScreen.new(game["title"]))
	else:
		_message.text = "That game would not start."
