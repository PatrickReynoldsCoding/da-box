class_name PinPad
extends VBoxContainer
## Number pad for the admin PIN. Works with arrows + Enter, and with number keys.

signal submitted(pin: String)

const MIN_DIGITS := 4
const MAX_DIGITS := 8
const DELETE := "Delete"
const OK_KEY := "OK"
const KEYS := ["1", "2", "3", "4", "5", "6", "7", "8", "9", DELETE, "0", OK_KEY]

var pin := ""
var _display: Label
var _grid: GridContainer


func _init() -> void:
	alignment = BoxContainer.ALIGNMENT_CENTER
	add_theme_constant_override("separation", 24)

	_display = Label.new()
	_display.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_display.add_theme_font_size_override("font_size", 72)
	add_child(_display)

	_grid = GridContainer.new()
	_grid.columns = 3
	_grid.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	_grid.add_theme_constant_override("h_separation", 16)
	_grid.add_theme_constant_override("v_separation", 16)
	add_child(_grid)

	for key in KEYS:
		var button := Button.new()
		button.text = key
		button.custom_minimum_size = Vector2(200, 100)
		button.focus_mode = Control.FOCUS_ALL
		button.add_theme_font_size_override("font_size", 48 if key.is_valid_int() else 32)
		button.pressed.connect(_press.bind(key))
		_grid.add_child(button)
	_refresh()


func clear() -> void:
	pin = ""
	_refresh()


func first_button() -> Button:
	return _grid.get_child(0) as Button


func _unhandled_key_input(event: InputEvent) -> void:
	if not is_visible_in_tree() or not event.is_pressed():
		return
	var key_event := event as InputEventKey
	var typed := char(key_event.unicode) if key_event.unicode != 0 else ""
	if typed.is_valid_int():
		_press(typed)
	elif key_event.keycode == KEY_BACKSPACE:
		_press(DELETE)
	else:
		return
	get_viewport().set_input_as_handled()


func _press(key: String) -> void:
	match key:
		DELETE:
			pin = pin.left(-1)
		OK_KEY:
			if pin.length() >= MIN_DIGITS:
				submitted.emit(pin)
		_:
			if pin.length() < MAX_DIGITS:
				pin += key
	_refresh()


func _refresh() -> void:
	var dots := "●".repeat(pin.length())
	_display.text = dots if not dots.is_empty() else "- - - -"
