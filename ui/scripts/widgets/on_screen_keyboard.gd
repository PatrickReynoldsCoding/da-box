class_name OnScreenKeyboard
extends VBoxContainer
## Keyboard for typing with the controller: a Wi-Fi password (hidden), a search or a name.

signal submitted(text: String)
signal text_changed(text: String)

const LETTER_ROWS := ["1234567890", "qwertyuiop", "asdfghjkl", "zxcvbnm"]
const SYMBOL_ROWS := ["1234567890", "!@#$%^&*()", "-_=+[]{};:", "'\",.<>/?\\|`~"]
const SHIFT := "Shift"
const SYMBOLS := "#+="
const LETTERS := "abc"
const SPACE := "Space"
const DELETE := "Delete"
const DONE := "Done"
const SHOW := "Show"
const HIDE := "Hide"

var text := ""
var _shift := false
var _symbols := false
var _secret: bool
var _hidden: bool
var _max_length: int
var _display: Label
var _keys: VBoxContainer


## `secret`: show dots, with a Show/Hide key (for passwords). `max_length` 0 means no limit.
func _init(secret: bool = true, max_length: int = 0, initial_text: String = "") -> void:
	_secret = secret
	_hidden = secret
	_max_length = max_length
	text = initial_text
	add_theme_constant_override("separation", 16)
	_display = Label.new()
	_display.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_display.add_theme_font_size_override("font_size", 52)
	_display.add_theme_stylebox_override("normal", UiTheme.rounded_box(Color(0, 0, 0, 0.3), 20))
	add_child(_display)
	_keys = VBoxContainer.new()
	_keys.add_theme_constant_override("separation", 10)
	add_child(_keys)
	_build_keys()
	_refresh_display()


func first_button() -> Button:
	return (_keys.get_child(0) as HBoxContainer).get_child(0) as Button


func _unhandled_key_input(event: InputEvent) -> void:
	# A real keyboard also works.
	if not is_visible_in_tree() or not event.is_pressed():
		return
	var key_event := event as InputEventKey
	if key_event.keycode == KEY_BACKSPACE:
		_press(DELETE)
	elif key_event.unicode >= 32 and key_event.unicode != 127:
		_type(char(key_event.unicode))
	else:
		return
	get_viewport().set_input_as_handled()


func _build_keys() -> void:
	var focus_owner := get_viewport().gui_get_focus_owner() if is_inside_tree() else null
	var had_focus := focus_owner != null and _keys.is_ancestor_of(focus_owner)
	for row in _keys.get_children():
		_keys.remove_child(row)
		row.queue_free()
	var rows := SYMBOL_ROWS if _symbols else LETTER_ROWS
	for characters in rows:
		var keys: Array = []
		for character in characters:
			keys.append(character.to_upper() if _shift else character)
		_add_row(keys, 96)
	var bottom := [SHIFT, LETTERS if _symbols else SYMBOLS, SPACE, DELETE]
	if _secret:
		bottom.append(HIDE if not _hidden else SHOW)
	bottom.append(DONE)
	_add_row(bottom, 180)
	if had_focus:
		_focus_first_key.call_deferred()


func _focus_first_key() -> void:
	# The rebuild came from a key in the bottom row, so keep the focus there.
	var bottom_row := _keys.get_child(_keys.get_child_count() - 1) as HBoxContainer
	(bottom_row.get_child(0) as Button).grab_focus()


func _add_row(keys: Array, width: float) -> void:
	var row := HBoxContainer.new()
	row.alignment = BoxContainer.ALIGNMENT_CENTER
	row.add_theme_constant_override("separation", 10)
	for key in keys:
		var button := Button.new()
		button.text = key
		button.focus_mode = Control.FOCUS_ALL
		button.custom_minimum_size = Vector2(width if key.length() > 1 else 96, 84)
		button.add_theme_font_size_override("font_size", 36 if key.length() == 1 else 28)
		button.pressed.connect(_press.bind(key))
		row.add_child(button)
	_keys.add_child(row)


func _press(key: String) -> void:
	match key:
		SHIFT:
			_shift = not _shift
			_build_keys()
		SYMBOLS, LETTERS:
			_symbols = not _symbols
			_build_keys()
		SHOW, HIDE:
			_hidden = not _hidden
			_build_keys()
		SPACE:
			_type(" ")
			return
		DELETE:
			text = text.left(-1)
			text_changed.emit(text)
		DONE:
			submitted.emit(text)
		_:
			_type(key)
			return
	_refresh_display()


func _type(characters: String) -> void:
	if _max_length > 0 and text.length() + characters.length() > _max_length:
		return
	text += characters
	_refresh_display()
	text_changed.emit(text)


func _refresh_display() -> void:
	var shown := "•".repeat(text.length()) if _hidden else text
	_display.text = shown if not shown.is_empty() else " "
