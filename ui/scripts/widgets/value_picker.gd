class_name ValuePicker
extends Button
## A number or time of day the parent changes with Up and Down.
## Press Enter to start changing it, then Enter or Esc to finish.
## It starts with no value ("--"). The first Up or Down sets the start value.

signal value_changed(value: int)
## Emitted when the parent presses Enter or Esc to stop changing a value that is set.
signal editing_finished

enum Format { MINUTES, TIME_OF_DAY }

const UNSET := -1

var value := UNSET
var _format: Format
var _minimum: int
var _maximum: int
var _step: int
var _first_value: int
var _editing := false


func _init(format: Format, minimum: int, maximum: int, step: int, first_value: int) -> void:
	_format = format
	_minimum = minimum
	_maximum = maximum
	_step = step
	_first_value = first_value
	custom_minimum_size = Vector2(260, 96)
	focus_mode = Control.FOCUS_ALL
	add_theme_font_size_override("font_size", 44)
	pressed.connect(_toggle_editing)
	_refresh()


func set_value(new_value: int) -> void:
	value = clampi(new_value, _minimum, _maximum) if new_value != UNSET else UNSET
	_refresh()


func has_value() -> bool:
	return value != UNSET


static func format_minutes(minutes: int) -> String:
	var hours := minutes / 60
	var rest := minutes % 60
	if hours == 0:
		return "%d min" % rest
	if rest == 0:
		return "%d h" % hours
	return "%d h %d min" % [hours, rest]


static func format_time(minutes_after_midnight: int) -> String:
	return "%02d:%02d" % [minutes_after_midnight / 60, minutes_after_midnight % 60]


func _gui_input(event: InputEvent) -> void:
	if not _editing:
		return
	if event.is_action_pressed("ui_up", true):
		_change(1)
	elif event.is_action_pressed("ui_down", true):
		_change(-1)
	elif event.is_action_pressed("ui_cancel"):
		_stop_editing()
	elif event.is_action_pressed("ui_left") or event.is_action_pressed("ui_right"):
		pass
	else:
		return
	accept_event()


func _toggle_editing() -> void:
	if _editing:
		_stop_editing()
	else:
		_editing = true
		_refresh()


func _stop_editing() -> void:
	_editing = false
	_refresh()
	if has_value():
		editing_finished.emit()


func _change(direction: int) -> void:
	if value == UNSET:
		value = _first_value
	else:
		value = clampi(value + direction * _step, _minimum, _maximum)
	_refresh()
	value_changed.emit(value)


func _refresh() -> void:
	var shown := "--"
	if value != UNSET:
		shown = format_minutes(value) if _format == Format.MINUTES else format_time(value)
	text = ("▲ %s ▼" % shown) if _editing else shown
	var edit_colour := UiTheme.GOOD if _editing else UiTheme.FOCUS
	add_theme_stylebox_override("focus", UiTheme.rounded_box(edit_colour, 24, 0))
