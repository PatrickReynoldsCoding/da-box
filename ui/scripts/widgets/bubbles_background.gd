class_name BubblesBackground
extends Control
## Gradient background with soft bubbles that float up slowly.

const BUBBLE_COUNT := 18
const BUBBLE_COLOURS := [UiTheme.TV, UiTheme.FILMS, UiTheme.MUSIC, UiTheme.GAMES]

var _bubbles: Array[Dictionary] = []
var _gradient := GradientTexture2D.new()


func _ready() -> void:
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	mouse_filter = Control.MOUSE_FILTER_IGNORE
	var gradient := Gradient.new()
	gradient.set_color(0, UiTheme.BACKGROUND_TOP)
	gradient.set_color(1, UiTheme.BACKGROUND_BOTTOM)
	_gradient.gradient = gradient
	_gradient.fill_from = Vector2(0, 0)
	_gradient.fill_to = Vector2(0, 1)
	var random := RandomNumberGenerator.new()
	random.seed = 7
	for i in BUBBLE_COUNT:
		_bubbles.append({
			"x": random.randf(),
			"y": random.randf(),
			"radius": random.randf_range(30, 140),
			"speed": random.randf_range(0.004, 0.018),
			"colour": BUBBLE_COLOURS[i % BUBBLE_COLOURS.size()],
		})


func _process(delta: float) -> void:
	for bubble in _bubbles:
		bubble["y"] -= bubble["speed"] * delta
		if bubble["y"] < -0.2:
			bubble["y"] = 1.2
	queue_redraw()


func _draw() -> void:
	draw_texture_rect(_gradient, Rect2(Vector2.ZERO, size), false)
	for bubble in _bubbles:
		var colour: Color = bubble["colour"]
		colour.a = 0.10
		draw_circle(Vector2(bubble["x"] * size.x, bubble["y"] * size.y), bubble["radius"], colour)
