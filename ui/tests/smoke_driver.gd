extends Node
## Dev-only UI smoke test. Started by `--smoke-test=<folder>` (see Api._ready).
## Presses keys like a parent would, goes through the setup and the main screens,
## and saves a screenshot after each important step. Needs the dev service and agent.

var _output_dir := ""
var _shot_number := 0


func _init(output_dir: String) -> void:
	_output_dir = output_dir


func _ready() -> void:
	DirAccess.make_dir_recursive_absolute(_output_dir)
	_run.call_deferred()


func _run() -> void:
	await _wait(2.0)
	if Api.state.get("setup_required", false):
		await _run_setup()
	await _run_main_screens()
	print("SMOKE TEST DONE")
	get_tree().quit()


func _run_setup() -> void:
	await _shot("setup-01-welcome")
	await _press("ui_accept")
	await _wait(1.0)
	await _shot("setup-02-network")
	await _press_next()

	await _wait(0.6)
	for attempt in 2:
		for i in 8:
			await _key(KEY_BACKSPACE, 0)
		await _type_digits("2468")
		await _focus_and_press_button("OK")
	await _wait(0.5)

	await _shot("setup-04-timezone-regions")
	await _focus_and_press_button("Europe")
	await _focus_and_press_button("London")
	await _shot("setup-04-timezone-chosen")
	await _press_next()

	await _set_picker(8)
	await _shot("setup-05-quota")
	await _press_next()
	await _focus_and_press_button("Yes, share it")
	await _press_next()
	await _set_picker(1)
	await _press_next()

	await _focus_and_press_button("Games")
	await _focus_pickers_and_set(2, [1, 1])
	await _focus_and_press_button("Copy Monday to every day")
	await _shot("setup-08-game-window")
	await _press_next()

	await _focus_pickers_and_set(1, [1])
	await _focus_and_press_button("Copy Monday to every day")
	await _shot("setup-09-bedtime")
	await _press_next()

	await _focus_and_press_button("No, stop at bedtime")
	await _press_next()
	var usb_on_buttons := _buttons_with_text("On")
	for button in usb_on_buttons:
		button.grab_focus()
		await _press("ui_accept")
	await _shot("setup-11-usb")
	await _press_next()
	await _shot("setup-12-summary")
	await _focus_and_press_button("Finish setup")
	await _wait(2.0)
	await _shot("setup-12-done")
	await _focus_and_press_button("Start using da-box")
	await _wait(1.0)


func _run_main_screens() -> void:
	await _shot("home")
	await _press("ui_accept")
	await _wait(2.0)
	await _shot("films")
	await _press("ui_right")
	await _wait(0.5)
	await _shot("films-focus-second")
	await _press("ui_cancel")
	await _wait(0.5)
	await _press("ui_right")
	await _press("ui_accept")
	await _wait(2.0)
	await _shot("music")
	await _press("ui_accept")
	await _wait(1.5)
	await _shot("album")
	await _press("ui_accept")
	await _wait(2.5)
	await _shot("now-playing")
	await _focus_and_press_button_with_icon_action("stop")
	await _wait(1.5)
	await _shot("after-stop")
	await _run_tv()


func _run_tv() -> void:
	# Back to Home, then the TV tile (left of Films).
	for i in 3:
		await _press("ui_cancel")
	await _wait(0.5)
	var tv_tile := get_tree().root.find_child("TVTile", true, false) as Control
	if tv_tile == null:
		# At night the sleeping screen replaces Home.
		print("TV part skipped: no Home screen (night or quota used up?)")
		return
	tv_tile.grab_focus()
	await _press("ui_accept")
	await _wait(2.5)
	await _shot("tv-guide")
	await _press("ui_accept")
	await _wait(4.0)
	await _shot("tv-channel")
	await _press("ui_down")
	await _wait(4.0)
	await _shot("tv-channel-changed")
	await _press("ui_cancel")
	await _wait(1.5)
	await _shot("tv-back-to-guide")


# ---- Helpers ----

func _wait(seconds: float) -> void:
	await get_tree().create_timer(seconds).timeout


func _press(action: String) -> void:
	var down := InputEventAction.new()
	down.action = action
	down.pressed = true
	Input.parse_input_event(down)
	await get_tree().process_frame
	var up := InputEventAction.new()
	up.action = action
	up.pressed = false
	Input.parse_input_event(up)
	await _wait(0.25)


func _key(keycode: Key, unicode: int, wait: bool = true) -> void:
	var event := InputEventKey.new()
	event.keycode = keycode
	event.unicode = unicode
	event.pressed = true
	Input.parse_input_event(event)
	await get_tree().process_frame
	event = event.duplicate()
	event.pressed = false
	Input.parse_input_event(event)
	if wait:
		await _wait(0.1)


func _type_digits(digits: String) -> void:
	for digit in digits:
		await _key((KEY_0 + int(digit)) as Key, digit.unicode_at(0))


func _press_next() -> void:
	await _wait(0.3)
	await _focus_and_press_button("Next")
	await _wait(0.6)


func _buttons_with_text(text: String) -> Array[Button]:
	var found: Array[Button] = []
	_collect_buttons(get_tree().root, text, found)
	return found


func _collect_buttons(node: Node, text: String, found: Array[Button]) -> void:
	if node is Button and node.is_visible_in_tree() and (node as Button).text == text:
		found.append(node)
	for child in node.get_children():
		_collect_buttons(child, text, found)


func _focus_and_press_button(text: String) -> void:
	var buttons := _buttons_with_text(text)
	if buttons.is_empty():
		push_error("Smoke test: no visible button '%s'" % text)
		await _shot("missing-" + text.to_snake_case())
		return
	buttons[0].grab_focus()
	await _press("ui_accept")
	await _wait(0.4)


func _focus_and_press_button_with_icon_action(action: String) -> void:
	var stop_kinds := {"stop": Icon.Kind.STOP}
	var found: Array[Button] = []
	_collect_icon_buttons(get_tree().root, stop_kinds[action], found)
	if found.is_empty():
		push_error("Smoke test: no button with icon '%s'" % action)
		return
	found[0].grab_focus()
	await _press("ui_accept")


func _collect_icon_buttons(node: Node, kind: Icon.Kind, found: Array[Button]) -> void:
	if node is Icon and (node as Icon).kind == kind and node.get_parent() is Button:
		found.append(node.get_parent())
	for child in node.get_children():
		_collect_icon_buttons(child, kind, found)


## Sets the first value picker on the page by pressing Enter, Up `ups` times, then Enter.
func _set_picker(ups: int) -> void:
	var picker := _visible_pickers()[0]
	picker.grab_focus()
	await _edit_picker(ups)


## Sets the first `count` pickers on the page (for example From and To on Monday).
func _focus_pickers_and_set(count: int, ups: Array) -> void:
	var pickers := _visible_pickers()
	for i in count:
		pickers[i].grab_focus()
		await _edit_picker(ups[i])


func _edit_picker(ups: int) -> void:
	await _press("ui_accept")
	for i in ups:
		await _press("ui_up")
	await _press("ui_accept")


func _visible_pickers() -> Array[ValuePicker]:
	var found: Array[ValuePicker] = []
	_collect_pickers(get_tree().root, found)
	return found


func _collect_pickers(node: Node, found: Array[ValuePicker]) -> void:
	if node is ValuePicker and node.is_visible_in_tree() and not (node as ValuePicker).disabled:
		found.append(node)
	for child in node.get_children():
		_collect_pickers(child, found)


var _frame_drawn := false


func _shot(name: String) -> void:
	# macOS stops drawing a hidden window (for example when the screen is locked),
	# so do not wait for a drawn frame for ever.
	_frame_drawn = false
	RenderingServer.frame_post_draw.connect(func() -> void: _frame_drawn = true, CONNECT_ONE_SHOT)
	var deadline := Time.get_ticks_msec() + 2000
	while not _frame_drawn and Time.get_ticks_msec() < deadline:
		await get_tree().process_frame
	_shot_number += 1
	if not _frame_drawn:
		print("screenshot skipped (window not drawing): ", name)
		return
	var image := get_viewport().get_texture().get_image()
	var path := "%s/%02d-%s.png" % [_output_dir, _shot_number, name]
	image.save_png(path)
	print("screenshot: ", path)
