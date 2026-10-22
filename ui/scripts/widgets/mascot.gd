class_name Mascot
extends Control
## "Boxy", a small TV with a face. It bobs, blinks, and says something useful.

const BODY_SIZE := Vector2(150, 120)

var _time := 0.0
var _blink_at := 2.0
var _bubble: Label


func _ready() -> void:
	custom_minimum_size = Vector2(560, 200)
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	_bubble = Label.new()
	_bubble.add_theme_font_size_override("font_size", 30)
	_bubble.add_theme_color_override("font_color", UiTheme.BACKGROUND_TOP)
	_bubble.add_theme_stylebox_override("normal", UiTheme.rounded_box(UiTheme.TEXT, 24, 18))
	_bubble.position = Vector2(0, 30)
	add_child(_bubble)
	Api.limits_changed.connect(func(_limits: Dictionary) -> void: _refresh_text())
	_refresh_text()


func _process(delta: float) -> void:
	_time += delta
	if _time > _blink_at + 0.15:
		_blink_at = _time + randf_range(2.0, 5.0)
	# Keep the bubble just left of Boxy's head (the size is only known after layout).
	_bubble.position = Vector2(size.x - BODY_SIZE.x - 30 - _bubble.get_minimum_size().x, 60 + sin(_time * 2.2) * 6.0)
	queue_redraw()


func _refresh_text() -> void:
	_bubble.text = say(Api.limits, Time.get_time_dict_from_system()["hour"])


static func say(limits: Dictionary, hour: int) -> String:
	if limits.get("warning") is String:
		return limits["warning"] + "!"
	if not limits.is_empty() and not limits.get("unlimited", true):
		if limits.get("games_open", false):
			return "Games are open!"
		if String(limits.get("games_message", "")).begins_with("Games open at"):
			return String(limits["games_message"]) + "!"
	var greetings := {5: "Good morning!", 12: "Good afternoon!", 17: "Good evening!"}
	var greeting := "Hello!"
	for start in greetings:
		if hour >= start:
			greeting = greetings[start]
	return greeting


func _draw() -> void:
	var bob := sin(_time * 2.2) * 6.0
	var origin := Vector2(size.x - BODY_SIZE.x - 10, 40 + bob)
	var body := Rect2(origin, BODY_SIZE)
	# Antennae
	draw_line(origin + Vector2(50, 0), origin + Vector2(30, -28), UiTheme.TEXT, 6, true)
	draw_line(origin + Vector2(100, 0), origin + Vector2(122, -28), UiTheme.TEXT, 6, true)
	draw_circle(origin + Vector2(30, -28), 8, UiTheme.FOCUS)
	draw_circle(origin + Vector2(122, -28), 8, UiTheme.TV)
	# Body and screen
	draw_style_box(UiTheme.rounded_box(UiTheme.GAMES, 28, 0), body)
	draw_style_box(UiTheme.rounded_box(UiTheme.BACKGROUND_TOP.lightened(0.15), 20, 0), body.grow(-14))
	# Eyes (closed while blinking) and smile
	var blinking := _time >= _blink_at and _time < _blink_at + 0.15
	for x in [55.0, 95.0]:
		var eye := origin + Vector2(x, 50)
		if blinking:
			draw_line(eye - Vector2(8, 0), eye + Vector2(8, 0), UiTheme.TEXT, 5, true)
		else:
			draw_circle(eye, 9, UiTheme.TEXT)
	draw_arc(origin + Vector2(75, 68), 20, 0.3, PI - 0.3, 16, UiTheme.FOCUS, 5, true)
	# Feet
	draw_rect(Rect2(origin + Vector2(30, BODY_SIZE.y), Vector2(20, 10)), UiTheme.GAMES)
	draw_rect(Rect2(origin + Vector2(100, BODY_SIZE.y), Vector2(20, 10)), UiTheme.GAMES)
