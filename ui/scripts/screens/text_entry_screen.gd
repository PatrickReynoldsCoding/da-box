class_name TextEntryScreen
extends Screen
## Type a line with the on-screen keyboard: an API key, a user name, a search. Done gives the
## text and closes; Back closes without it.

signal entered(text: String)

var keyboard: OnScreenKeyboard
var _title: String
var _hint: String
var _initial: String
var _secret: bool
var _max_length: int


func _init(title: String, hint: String = "", initial: String = "", secret: bool = false, max_length: int = 0) -> void:
	_title = title
	_hint = hint
	_initial = initial
	_secret = secret
	_max_length = max_length


func _ready() -> void:
	super()
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 30)
	column.add_child(header(_title, UiTheme.WARNING))
	if not _hint.is_empty():
		var hint := UiTheme.muted_label(_hint, UiTheme.FONT_SIZE)
		hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		column.add_child(hint)
	keyboard = OnScreenKeyboard.new(_secret, _max_length, _initial)
	keyboard.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	keyboard.submitted.connect(_on_submitted)
	column.add_child(keyboard)
	page_margin(column)


func default_focus() -> Control:
	return keyboard.first_button()


func _on_submitted(text: String) -> void:
	entered.emit(text.strip_edges())
	close_screen.emit()
