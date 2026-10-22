class_name ChoiceRow
extends HBoxContainer
## A row of big buttons where the parent picks one option. Nothing is picked at the start.

signal changed(value: Variant)

var value: Variant = null
var _buttons: Dictionary = {}


## options: Array of [value, label] pairs.
func _init(options: Array, button_width: float = 260.0, button_height: float = 96.0) -> void:
	add_theme_constant_override("separation", 24)
	for option in options:
		var button := Button.new()
		button.text = option[1]
		button.toggle_mode = true
		button.focus_mode = Control.FOCUS_ALL
		button.custom_minimum_size = Vector2(button_width, button_height)
		button.add_theme_stylebox_override("pressed", UiTheme.rounded_box(UiTheme.GOOD, 24))
		button.add_theme_stylebox_override("hover_pressed", UiTheme.rounded_box(UiTheme.GOOD, 24))
		button.add_theme_color_override("font_pressed_color", UiTheme.BACKGROUND_TOP)
		var option_value: Variant = option[0]
		button.pressed.connect(func() -> void: select(option_value))
		_buttons[option_value] = button
		add_child(button)


func has_value() -> bool:
	return value != null


func select(option_value: Variant) -> void:
	value = option_value
	for key in _buttons:
		_buttons[key].set_pressed_no_signal(key == option_value)
	changed.emit(value)


func first_button() -> Button:
	return get_child(0) as Button
