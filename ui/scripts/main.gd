extends Control
## Root of the box UI. Shows one screen at a time, keeps a stack for Back, and
## watches the box state (setup needed, parent mode).

const STATE_POLL_SECONDS := 3.0

var _stack: Array[Screen] = []
var _layer: Control
var _parent_badge: Label
var _warning: Label


func _ready() -> void:
	if "--hide-cursor" in OS.get_cmdline_user_args():
		Input.mouse_mode = Input.MOUSE_MODE_HIDDEN
	theme = UiTheme.build()
	add_child(BubblesBackground.new())
	_layer = Control.new()
	_layer.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(_layer)
	_parent_badge = _make_parent_badge()
	add_child(_parent_badge)
	_warning = _make_warning()
	add_child(_warning)
	Api.limits_changed.connect(_on_limits_changed)

	Api.state_changed.connect(_on_state_changed)
	var timer := Timer.new()
	timer.wait_time = STATE_POLL_SECONDS
	timer.autostart = true
	timer.timeout.connect(_poll_state)
	add_child(timer)

	_replace_all(ConnectingScreen.new())
	_poll_state()


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("ui_cancel") and not _stack.is_empty():
		get_viewport().set_input_as_handled()
		_stack.back().go_back()


func _poll_state() -> void:
	var reachable := await Api.refresh_state()
	if reachable and not Api.state.get("setup_required", true):
		await Api.refresh_limits()
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
		below.visible = false
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
	if remembered is Control and is_instance_valid(remembered) and remembered.is_visible_in_tree():
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
	badge.set_anchors_and_offsets_preset(Control.PRESET_TOP_RIGHT, Control.PRESET_MODE_MINSIZE, 24)
	badge.grow_horizontal = Control.GROW_DIRECTION_BEGIN
	badge.visible = false
	return badge
