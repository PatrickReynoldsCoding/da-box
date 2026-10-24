class_name PowerMenuScreen
extends Screen
## The power menu (DESIGN_CORRECTIONS_2.md, part 9): a small panel over the screen with Shut down
## and Cancel. Cancel has the focus first, so a kid who opens it by accident does not turn the box
## off; B or Esc means Cancel. It opens with Esc or B on Home, or the controller's Guide button
## (Xbox, PlayStation or Home button) on any screen but a playing video or game.

var cancel_button: Button
var shut_down_button: Button
var _message: Label


func _init() -> void:
	overlay = true


func _ready() -> void:
	super()
	var dim := ColorRect.new()
	dim.color = Color(0, 0, 0, 0.6)
	dim.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(dim)
	var centre := CenterContainer.new()
	centre.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(centre)
	var panel := PanelContainer.new()
	panel.add_theme_stylebox_override("panel", UiTheme.rounded_box(UiTheme.BACKGROUND_BOTTOM, 32, 48))
	centre.add_child(panel)
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 36)
	column.add_child(UiTheme.title_label("Power"))
	var buttons := HBoxContainer.new()
	buttons.add_theme_constant_override("separation", 30)
	cancel_button = Button.new()
	cancel_button.text = "Cancel"
	cancel_button.custom_minimum_size = Vector2(300, 100)
	cancel_button.pressed.connect(go_back)
	buttons.add_child(cancel_button)
	shut_down_button = Button.new()
	shut_down_button.text = "Shut down"
	shut_down_button.custom_minimum_size = Vector2(340, 100)
	shut_down_button.pressed.connect(_shut_down)
	buttons.add_child(shut_down_button)
	column.add_child(buttons)
	_message = UiTheme.muted_label("", UiTheme.FONT_SIZE)
	column.add_child(_message)
	panel.add_child(column)
	# The focus stays in the panel: the screen behind it is only to look at.
	for button: Button in [cancel_button, shut_down_button]:
		var other := shut_down_button if button == cancel_button else cancel_button
		for side in [SIDE_TOP, SIDE_BOTTOM]:
			button.set_focus_neighbor(side, button.get_path())
		button.set_focus_neighbor(SIDE_LEFT, other.get_path() if button == shut_down_button else button.get_path())
		button.set_focus_neighbor(SIDE_RIGHT, other.get_path() if button == cancel_button else button.get_path())
		button.focus_next = other.get_path()
		button.focus_previous = other.get_path()


func default_focus() -> Control:
	return cancel_button


func _shut_down() -> void:
	cancel_button.disabled = true
	shut_down_button.disabled = true
	_message.text = "Turning off…"
	var reply := await Api.service_post("/box/power/off")
	if not reply.ok and is_inside_tree():
		_message.text = Api.error_text(reply, "The box could not turn off.")
		cancel_button.disabled = false
		shut_down_button.disabled = false
		cancel_button.grab_focus()
