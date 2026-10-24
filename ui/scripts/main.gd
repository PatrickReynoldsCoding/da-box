extends Control
## Root of the box UI. Shows one screen at a time, keeps a stack for Back, and
## watches the box state (setup needed, parent mode).

const STATE_POLL_SECONDS := 3.0
const TOAST_SECONDS := 12.0

var _stack: Array[Screen] = []
var _layer: Control
var _parent_badge: Label
var _warning: Label
var _toast: Label
var _toast_timer: Timer
## The last Copy from USB job whose end the TV has shown (-1: none seen yet).
var _announced_copy := -1


func _ready() -> void:
	if "--hide-cursor" in OS.get_cmdline_user_args():
		Input.mouse_mode = Input.MOUSE_MODE_HIDDEN
	add_controller_buttons()
	theme = UiTheme.build()
	add_child(BubblesBackground.new())
	_layer = Control.new()
	_layer.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(_layer)
	_parent_badge = _make_parent_badge()
	add_child(_parent_badge)
	_warning = _make_warning()
	add_child(_warning)
	_toast = _make_toast()
	add_child(_toast)
	_toast_timer = Timer.new()
	_toast_timer.one_shot = true
	_toast_timer.timeout.connect(func() -> void: _toast.visible = false)
	add_child(_toast_timer)
	Api.limits_changed.connect(_on_limits_changed)
	Api.copy_changed.connect(_on_copy_changed)

	Api.state_changed.connect(_on_state_changed)
	var timer := Timer.new()
	timer.wait_time = STATE_POLL_SECONDS
	timer.autostart = true
	timer.timeout.connect(_poll_state)
	add_child(timer)

	_replace_all(ConnectingScreen.new())
	_poll_state()


## Godot's built-in ui_accept and ui_cancel have keys only, so a controller could move but not
## press anything. A (the bottom face button) is Enter; B (the right one) and Back/Select are Esc.
## Godot names buttons by position, so this is the same on Xbox, PlayStation and 8BitDo pads.
static func add_controller_buttons() -> void:
	var buttons := {
		"ui_accept": [JOY_BUTTON_A],
		"ui_cancel": [JOY_BUTTON_B, JOY_BUTTON_BACK],
	}
	for action: String in buttons:
		for button: JoyButton in buttons[action]:
			var event := InputEventJoypadButton.new()
			event.button_index = button
			# device -1: every controller, also one plugged in later.
			event.device = -1
			if not InputMap.action_has_event(action, event):
				InputMap.action_add_event(action, event)


## The controller's Guide button: the Xbox button, the PlayStation button, the Home button on
## 8BitDo and Nintendo-style pads. It opens the power menu.
static func is_guide_button(event: InputEvent) -> bool:
	var button := event as InputEventJoypadButton
	return button != null and button.pressed and button.button_index == JOY_BUTTON_GUIDE


## Not over a playing video or game, and not twice.
func can_open_power_menu() -> bool:
	var top := _top()
	return top != null and not (top is VideoScreen or top is GameScreen or top is PowerMenuScreen)


func _unhandled_input(event: InputEvent) -> void:
	if is_guide_button(event):
		get_viewport().set_input_as_handled()
		if can_open_power_menu():
			_push(PowerMenuScreen.new())
		return
	if event.is_action_pressed("ui_cancel") and not _stack.is_empty():
		get_viewport().set_input_as_handled()
		_stack.back().go_back()


func _poll_state() -> void:
	var reachable := await Api.refresh_state()
	if reachable and not Api.state.get("setup_required", true):
		await Api.refresh_limits()
		await Api.refresh_copy()
	if not reachable and not (_top() is ConnectingScreen):
		_replace_all(ConnectingScreen.new())
	elif reachable and _top() is ConnectingScreen:
		_show_for_state(Api.state)


func _on_state_changed(state: Dictionary) -> void:
	_parent_badge.visible = state.get("parent_mode", false)
	if _top() is ConnectingScreen:
		return
	var in_setup := not _stack.is_empty() and _stack[0] is SetupScreen
	var setup_required: bool = state.get("setup_required", false)
	# The admin app can ask for the setup again. A finished setup moves on by itself.
	if setup_required and not in_setup:
		_show_for_state(state)


func _on_limits_changed(limits: Dictionary) -> void:
	var warning: Variant = limits.get("warning")
	_warning.visible = warning is String
	_warning.text = warning if warning is String else ""
	var shutting_down: bool = limits.get("shutdown_at") != null
	if shutting_down and not (_top() is SleepingScreen):
		_replace_all(SleepingScreen.new())
	elif not shutting_down and _top() is SleepingScreen:
		# The parent gave extra time.
		_replace_all(HomeScreen.new())


## When a Copy from USB ends, say so on the TV (and over a film or game, through the agent).
func _on_copy_changed(progress: Dictionary) -> void:
	if progress.is_empty():
		return
	var job := int(progress.get("job_id", 0))
	var ended: bool = progress.get("state") in ["done", "stopped", "failed"]
	if _announced_copy < 0:
		# The first look after start-up: a result from before is not news.
		_announced_copy = job - 1 if progress.get("state") == "copying" else job
		return
	if not ended or job <= _announced_copy:
		return
	_announced_copy = job
	var message: String = progress.get("message") if progress.get("message") is String else "The copy from USB ended."
	var colour := UiTheme.GOOD if progress.get("state") == "done" else UiTheme.WARNING
	_toast.add_theme_stylebox_override("normal", UiTheme.rounded_box(colour, 24, 20))
	_toast.text = message
	_toast.visible = true
	_toast_timer.start(TOAST_SECONDS)
	Api.agent_post("/notify", {"message": message.left(200)})


func _make_toast() -> Label:
	var label := Label.new()
	label.add_theme_font_size_override("font_size", 36)
	label.add_theme_color_override("font_color", UiTheme.BACKGROUND_TOP)
	label.set_anchors_and_offsets_preset(Control.PRESET_CENTER_BOTTOM, Control.PRESET_MODE_MINSIZE, 40)
	label.grow_horizontal = Control.GROW_DIRECTION_BOTH
	label.grow_vertical = Control.GROW_DIRECTION_BEGIN
	label.visible = false
	return label


func _make_warning() -> Label:
	var label := Label.new()
	label.add_theme_font_size_override("font_size", 40)
	label.add_theme_color_override("font_color", UiTheme.BACKGROUND_TOP)
	label.add_theme_stylebox_override("normal", UiTheme.rounded_box(UiTheme.WARNING, 24, 20))
	label.set_anchors_and_offsets_preset(Control.PRESET_CENTER_TOP, Control.PRESET_MODE_MINSIZE, 24)
	label.grow_horizontal = Control.GROW_DIRECTION_BOTH
	label.visible = false
	return label


func _show_for_state(state: Dictionary) -> void:
	if state.get("setup_required", false):
		var setup := SetupScreen.new()
		setup.finished.connect(func() -> void: _replace_all(HomeScreen.new()))
		_replace_all(setup)
	else:
		_replace_all(HomeScreen.new())


func _top() -> Screen:
	return _stack.back() if not _stack.is_empty() else null


func _replace_all(screen: Screen) -> void:
	for old in _stack:
		old.queue_free()
	_stack.clear()
	_push(screen)


func _push(screen: Screen) -> void:
	if not _stack.is_empty():
		var below: Screen = _stack.back()
		# Remember the focus, so Back returns to the same tile.
		below.set_meta("last_focus", get_viewport().gui_get_focus_owner())
		below.visible = screen.overlay
	_stack.append(screen)
	screen.open_screen.connect(_push)
	screen.close_screen.connect(_pop.bind(screen))
	_layer.add_child(screen)
	_activate(screen)


func _pop(screen: Screen) -> void:
	if _stack.size() <= 1 or _stack.back() != screen:
		return
	_stack.pop_back()
	screen.queue_free()
	var below: Screen = _stack.back()
	below.visible = true
	_activate(below)


func _activate(screen: Screen) -> void:
	screen.on_shown()
	_focus_default.call_deferred(screen)


func _focus_default(screen: Screen) -> void:
	if not is_instance_valid(screen):
		return
	var remembered: Variant = null
	if screen.has_meta("last_focus"):
		remembered = screen.get_meta("last_focus")
		screen.remove_meta("last_focus")
	# The remembered control may be gone (a list that loaded again), so check that first.
	if is_instance_valid(remembered) and remembered is Control and remembered.is_visible_in_tree():
		remembered.grab_focus()
		return
	var target := screen.default_focus()
	if target != null and target.is_inside_tree():
		target.grab_focus()


func _make_parent_badge() -> Label:
	var badge := Label.new()
	badge.text = "Parent mode"
	badge.add_theme_font_size_override("font_size", 28)
	badge.add_theme_color_override("font_color", UiTheme.BACKGROUND_TOP)
	badge.add_theme_stylebox_override("normal", UiTheme.rounded_box(UiTheme.FOCUS, 16, 12))
	badge.set_anchors_and_offsets_preset(Control.PRESET_BOTTOM_LEFT, Control.PRESET_MODE_MINSIZE, 24)
	badge.grow_vertical = Control.GROW_DIRECTION_BEGIN
	badge.visible = false
	return badge
