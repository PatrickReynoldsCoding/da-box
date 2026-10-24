class_name Icon
extends Control
## Simple drawn icons, so the UI needs no image files or emoji font.

enum Kind { TV, FILM, MUSIC, GAME, PLAY, PAUSE, NEXT, PREVIOUS, STOP, USB, GEAR }

var kind: Kind
var colour: Color


func _init(icon_kind: Kind, icon_colour: Color = UiTheme.TEXT, icon_size: float = 160.0) -> void:
	kind = icon_kind
	colour = icon_colour
	custom_minimum_size = Vector2(icon_size, icon_size)
	mouse_filter = Control.MOUSE_FILTER_IGNORE


func _draw() -> void:
	# Never bigger than the asked size, and always centred in the space it gets.
	var extent := minf(minf(size.x, size.y), custom_minimum_size.x)
	var unit := extent / 10.0
	var origin := (size - Vector2(extent, extent)) / 2.0
	var drawers := {
		Kind.TV: _draw_tv,
		Kind.FILM: _draw_film,
		Kind.MUSIC: _draw_music,
		Kind.GAME: _draw_game,
		Kind.PLAY: _draw_play,
		Kind.PAUSE: _draw_pause,
		Kind.NEXT: _draw_next,
		Kind.PREVIOUS: _draw_previous,
		Kind.STOP: _draw_stop,
		Kind.USB: _draw_usb,
		Kind.GEAR: _draw_gear,
	}
	drawers[kind].call(origin, unit)


func _point(origin: Vector2, unit: float, x: float, y: float) -> Vector2:
	return origin + Vector2(x, y) * unit


func _draw_tv(origin: Vector2, unit: float) -> void:
	draw_line(_point(origin, unit, 3.5, 0.8), _point(origin, unit, 5, 2.4), colour, unit * 0.5, true)
	draw_line(_point(origin, unit, 6.5, 0.8), _point(origin, unit, 5, 2.4), colour, unit * 0.5, true)
	var body := Rect2(_point(origin, unit, 0.5, 2.4), Vector2(9, 6.2) * unit)
	draw_rect(body, colour)
	draw_rect(body.grow(-unit * 0.9), colour.darkened(0.55))
	draw_rect(Rect2(_point(origin, unit, 2.2, 8.6), Vector2(1, 0.8) * unit), colour)
	draw_rect(Rect2(_point(origin, unit, 6.8, 8.6), Vector2(1, 0.8) * unit), colour)


func _draw_film(origin: Vector2, unit: float) -> void:
	var board := Rect2(_point(origin, unit, 0.8, 4), Vector2(8.4, 5.2) * unit)
	draw_rect(board, colour)
	var clapper := PackedVector2Array([
		_point(origin, unit, 0.6, 3.6), _point(origin, unit, 8.6, 1.0),
		_point(origin, unit, 9.1, 2.5), _point(origin, unit, 1.1, 5.0),
	])
	draw_colored_polygon(clapper, colour)
	for stripe in 3:
		var x := 2.4 + stripe * 2.2
		draw_line(_point(origin, unit, x, 3.0 - stripe * 0.6), _point(origin, unit, x + 0.9, 3.9 - stripe * 0.6 + 0.8), colour.darkened(0.55), unit * 0.6)


func _draw_music(origin: Vector2, unit: float) -> void:
	draw_circle(_point(origin, unit, 2.6, 7.8), unit * 1.6, colour)
	draw_circle(_point(origin, unit, 7.4, 6.8), unit * 1.6, colour)
	draw_rect(Rect2(_point(origin, unit, 3.6, 1.8), Vector2(0.8, 6) * unit), colour)
	draw_rect(Rect2(_point(origin, unit, 8.4, 0.8), Vector2(0.8, 6) * unit), colour)
	draw_colored_polygon(PackedVector2Array([
		_point(origin, unit, 3.6, 1.8), _point(origin, unit, 9.2, 0.8),
		_point(origin, unit, 9.2, 2.4), _point(origin, unit, 3.6, 3.4),
	]), colour)


func _draw_game(origin: Vector2, unit: float) -> void:
	var body := Rect2(_point(origin, unit, 0.5, 2.8), Vector2(9, 4.8) * unit)
	draw_rect(body, colour)
	draw_circle(_point(origin, unit, 2.2, 6.8), unit * 1.6, colour)
	draw_circle(_point(origin, unit, 7.8, 6.8), unit * 1.6, colour)
	var dark := colour.darkened(0.55)
	draw_rect(Rect2(_point(origin, unit, 1.6, 4.6), Vector2(2.4, 0.8) * unit), dark)
	draw_rect(Rect2(_point(origin, unit, 2.4, 3.8), Vector2(0.8, 2.4) * unit), dark)
	draw_circle(_point(origin, unit, 6.8, 4.4), unit * 0.6, dark)
	draw_circle(_point(origin, unit, 8.0, 5.4), unit * 0.6, dark)


func _draw_play(origin: Vector2, unit: float) -> void:
	draw_colored_polygon(PackedVector2Array([
		_point(origin, unit, 2.5, 1.5), _point(origin, unit, 8.5, 5), _point(origin, unit, 2.5, 8.5),
	]), colour)


func _draw_pause(origin: Vector2, unit: float) -> void:
	draw_rect(Rect2(_point(origin, unit, 2.2, 1.5), Vector2(2, 7) * unit), colour)
	draw_rect(Rect2(_point(origin, unit, 5.8, 1.5), Vector2(2, 7) * unit), colour)


func _draw_next(origin: Vector2, unit: float) -> void:
	draw_colored_polygon(PackedVector2Array([
		_point(origin, unit, 1.5, 2), _point(origin, unit, 6.5, 5), _point(origin, unit, 1.5, 8),
	]), colour)
	draw_rect(Rect2(_point(origin, unit, 6.8, 2), Vector2(1.6, 6) * unit), colour)


func _draw_previous(origin: Vector2, unit: float) -> void:
	draw_colored_polygon(PackedVector2Array([
		_point(origin, unit, 8.5, 2), _point(origin, unit, 3.5, 5), _point(origin, unit, 8.5, 8),
	]), colour)
	draw_rect(Rect2(_point(origin, unit, 1.6, 2), Vector2(1.6, 6) * unit), colour)


func _draw_stop(origin: Vector2, unit: float) -> void:
	draw_rect(Rect2(_point(origin, unit, 2, 2), Vector2(6, 6) * unit), colour)


## A USB stick: the plug at the top, the body below, an arrow into the box.
func _draw_usb(origin: Vector2, unit: float) -> void:
	draw_rect(Rect2(_point(origin, unit, 3.6, 0.6), Vector2(2.8, 2.2) * unit), colour)
	var dark := colour.darkened(0.55)
	draw_rect(Rect2(_point(origin, unit, 4.1, 1.1), Vector2(0.6, 0.6) * unit), dark)
	draw_rect(Rect2(_point(origin, unit, 5.3, 1.1), Vector2(0.6, 0.6) * unit), dark)
	draw_rect(Rect2(_point(origin, unit, 2.8, 2.8), Vector2(4.4, 6.6) * unit), colour)
	draw_line(_point(origin, unit, 5, 4.0), _point(origin, unit, 5, 7.6), dark, unit * 0.7, true)
	draw_colored_polygon(PackedVector2Array([
		_point(origin, unit, 3.8, 6.8), _point(origin, unit, 6.2, 6.8), _point(origin, unit, 5, 8.4),
	]), dark)


## A gear (Settings): eight teeth round a wheel with a hole.
func _draw_gear(origin: Vector2, unit: float) -> void:
	var centre := _point(origin, unit, 5, 5)
	for tooth in 8:
		var direction := Vector2.from_angle(tooth * TAU / 8.0)
		var side := direction.orthogonal() * unit * 0.8
		var inner := centre + direction * unit * 2.8
		var outer := centre + direction * unit * 4.4
		draw_colored_polygon(PackedVector2Array([inner - side, outer - side, outer + side, inner + side]), colour)
	draw_circle(centre, unit * 3.3, colour)
	draw_circle(centre, unit * 1.3, colour.darkened(0.55))
