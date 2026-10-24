class_name NameScreen
extends Screen
## Type a name with the on-screen keyboard (for example a playlist name). Done gives the name and closes.

signal named(text: String)

const MAX_LENGTH := 30

var keyboard: OnScreenKeyboard
var _title: String
var _initial: String
var _message: Label


func _init(title: String, initial: String = "") -> void:
	_title = title
	_initial = initial


func _ready() -> void:
	super()
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 30)
	column.add_child(header(_title, UiTheme.MUSIC))
	column.add_child(UiTheme.muted_label("Up to %d letters. Press Done when it is ready." % MAX_LENGTH))
	keyboard = OnScreenKeyboard.new(false, MAX_LENGTH, _initial)
	keyboard.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	keyboard.submitted.connect(_on_submitted)
	column.add_child(keyboard)
	_message = UiTheme.muted_label("")
	column.add_child(_message)
	page_margin(column)


func default_focus() -> Control:
	return keyboard.first_button()


func _on_submitted(text: String) -> void:
	var cleaned := " ".join(text.split(" ", false))
	if cleaned.is_empty():
		_message.text = "Type a name first."
		return
	close_screen.emit()
	named.emit(cleaned)
