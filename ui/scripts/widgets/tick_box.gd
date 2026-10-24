class_name TickBox
extends Button
## A big tick box for the TV. Enter ticks and unticks it. `some` draws a dash:
## part of a folder is ticked.

const BOX_SIZE := 48.0
const BOX_LEFT := 28.0

var some := false


func _init(label: String) -> void:
	toggle_mode = true
	text = label
	alignment = HORIZONTAL_ALIGNMENT_LEFT
	text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	clip_text = true
	focus_mode = Control.FOCUS_ALL
	custom_minimum_size.y = 84
	size_flags_horizontal = Control.SIZE_EXPAND_FILL
	var styles := {
		"normal": Color(1, 1, 1, 0.08), "hover": Color(1, 1, 1, 0.14), "pressed": Color(1, 1, 1, 0.08),
		"hover_pressed": Color(1, 1, 1, 0.14), "disabled": Color(1, 1, 1, 0.03), "focus": UiTheme.FOCUS,
	}
	for style in styles:
		var box := UiTheme.rounded_box(styles[style], 20)
		box.content_margin_left = BOX_LEFT * 2 + BOX_SIZE
		add_theme_stylebox_override(style, box)
	# Ticked is not "pressed" in looks: only the box shows it.
	add_theme_color_override("font_pressed_color", UiTheme.TEXT)
	add_theme_color_override("font_hover_pressed_color", UiTheme.TEXT)
	toggled.connect(func(_ticked: bool) -> void: queue_redraw())


func set_ticked(ticked: bool, part: bool = false) -> void:
	set_pressed_no_signal(ticked)
	some = part and not ticked
	queue_redraw()


func _draw() -> void:
	var box := Rect2(Vector2(BOX_LEFT, (size.y - BOX_SIZE) / 2.0), Vector2(BOX_SIZE, BOX_SIZE))
	var ink := UiTheme.BACKGROUND_TOP if has_focus() else UiTheme.TEXT
	if disabled:
		ink = UiTheme.DISABLED
	if button_pressed:
		draw_rect(box, UiTheme.GOOD)
		var tick := PackedVector2Array([
			box.position + Vector2(10, 25), box.position + Vector2(20, 36), box.position + Vector2(39, 13),
		])
		draw_polyline(tick, UiTheme.BACKGROUND_TOP, 6.0, true)
	else:
		draw_rect(box, ink, false, 5.0)
		if some:
			draw_line(box.position + Vector2(12, 24), box.position + Vector2(36, 24), ink, 6.0)
