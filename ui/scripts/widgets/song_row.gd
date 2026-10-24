class_name SongRow
extends HBoxContainer
## One song in a list: Enter plays it. An optional button on the right (Right arrow)
## adds it to a playlist ("+") or takes it off one ("−").

signal play_pressed
signal side_pressed

const ADD := "+"
const REMOVE := "−"

var play_button: Button
var side_button: Button


func _init(song: Dictionary, side: String = "", show_album: bool = false) -> void:
	add_theme_constant_override("separation", 16)
	play_button = Button.new()
	var details: String = song["artist"]
	if show_album:
		details += "  ·  " + String(song["album"])
	var badge := "   [USB]" if song.get("source") == "usb" else ""
	play_button.text = "%s   —   %s%s" % [song["title"], details, badge]
	play_button.alignment = HORIZONTAL_ALIGNMENT_LEFT
	play_button.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	play_button.clip_text = true
	play_button.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	play_button.custom_minimum_size.y = 84
	play_button.add_theme_stylebox_override("normal", UiTheme.rounded_box(Color(1, 1, 1, 0.08), 20))
	play_button.pressed.connect(func() -> void: play_pressed.emit())
	add_child(play_button)
	if not side.is_empty():
		side_button = Button.new()
		side_button.text = side
		side_button.custom_minimum_size = Vector2(110, 84)
		side_button.add_theme_font_size_override("font_size", 48)
		side_button.pressed.connect(func() -> void: side_pressed.emit())
		add_child(side_button)


func _ready() -> void:
	# Godot's nearest-neighbour search picks the wide row below over the small button on the
	# right, so Left and Right stay in the row.
	var right := side_button if side_button != null else play_button
	play_button.focus_neighbor_right = play_button.get_path_to(right)
	play_button.focus_neighbor_left = play_button.get_path_to(play_button)
	if side_button != null:
		side_button.focus_neighbor_left = side_button.get_path_to(play_button)
		side_button.focus_neighbor_right = side_button.get_path_to(side_button)


## Only songs on the box can go on a playlist.
static func can_add(song: Dictionary) -> bool:
	return song.get("source") == "box"
