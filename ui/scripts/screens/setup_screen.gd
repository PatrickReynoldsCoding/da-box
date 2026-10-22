class_name SetupScreen
extends Screen
## First-run setup on the TV (design doc section 4). The parent picks every setting.
## Nothing is filled in: each value shows "--" until the parent sets it.

signal finished

const DAYS := [
	["mon", "Monday"], ["tue", "Tuesday"], ["wed", "Wednesday"], ["thu", "Thursday"],
	["fri", "Friday"], ["sat", "Saturday"], ["sun", "Sunday"],
]
const MINUTES_PER_DAY := 24 * 60
const TIME_STEP := 15


class Step:
	var title: String
	var page: Control
	var is_ready: Callable
	var focus: Callable
	## Optional. Returns true if Back was handled inside the step.
	var back: Callable
	## Optional. Runs each time the step shows.
	var enter: Callable

	func _init(step_title: String, step_page: Control, ready_check: Callable, focus_target: Callable) -> void:
		title = step_title
		page = step_page
		is_ready = ready_check
		focus = focus_target


var _steps: Array[Step] = []
var _index := 0
var _step_label: Label
var _title_label: Label
var _page_holder: MarginContainer
var _back_button: Button
var _next_button: Button

var _network_connected := false
var _network_status: Label
var _wifi_button: Button
var _wifi_list: VBoxContainer
var _wifi_prompt: Label
var _wifi_keyboard: OnScreenKeyboard
var _wifi_ssid := ""

var _pin := ""
var _pin_first := ""
var _pin_pad: PinPad
var _pin_message: Label

var _timezone := ""
var _timezones: PackedStringArray = []
var _timezone_label: Label
var _timezone_grid: GridContainer

var _quota: ValuePicker
var _shared_quota: ChoiceRow
var _overrun: ValuePicker
var _game_rows: Dictionary = {}
var _game_message: Label
var _bedtimes: Dictionary = {}
var _bedtime_overrun: ChoiceRow
var _usb_playback: ChoiceRow
var _usb_games: ChoiceRow
var _finish_page: VBoxContainer


func _ready() -> void:
	super()
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 24)
	_step_label = UiTheme.muted_label("")
	column.add_child(_step_label)
	_title_label = UiTheme.title_label("")
	column.add_child(_title_label)

	_page_holder = MarginContainer.new()
	_page_holder.size_flags_vertical = Control.SIZE_EXPAND_FILL
	column.add_child(_page_holder)

	var footer := HBoxContainer.new()
	_back_button = Button.new()
	_back_button.text = "Back"
	_back_button.custom_minimum_size = Vector2(240, 90)
	_back_button.pressed.connect(go_back)
	footer.add_child(_back_button)
	var spacer := Control.new()
	spacer.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	footer.add_child(spacer)
	_next_button = Button.new()
	_next_button.text = "Next"
	_next_button.custom_minimum_size = Vector2(300, 90)
	_next_button.add_theme_stylebox_override("normal", UiTheme.rounded_box(UiTheme.GOOD.darkened(0.3), 24))
	_next_button.pressed.connect(_next)
	footer.add_child(_next_button)
	column.add_child(footer)
	page_margin(column)

	_build_steps()
	_show_step(0)


func _exit_tree() -> void:
	# Pages of steps that are not showing are outside the tree, so free them here.
	for step in _steps:
		if not step.page.is_inside_tree():
			step.page.queue_free()


func _process(_delta: float) -> void:
	_update_next_button()


func _update_next_button() -> void:
	if _steps.is_empty():
		return
	_next_button.disabled = not _steps[_index].is_ready.call()
	_next_button.focus_mode = Control.FOCUS_NONE if _next_button.disabled else Control.FOCUS_ALL


func default_focus() -> Control:
	return _steps[_index].focus.call() if not _steps.is_empty() else null


func go_back() -> void:
	var step := _steps[_index]
	if step.back.is_valid() and step.back.call():
		return
	if _index > 0 and _index < _steps.size() - 1:
		_show_step(_index - 1)


func _next() -> void:
	if _index < _steps.size() - 1 and _steps[_index].is_ready.call():
		_show_step(_index + 1)


func _show_step(index: int) -> void:
	_index = index
	var step := _steps[index]
	for child in _page_holder.get_children():
		_page_holder.remove_child(child)
	step.page.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_page_holder.add_child(step.page)
	_step_label.text = "Setup  ·  Step %d of %d" % [index + 1, _steps.size()]
	_title_label.text = step.title
	var last := index == _steps.size() - 1
	_next_button.visible = not last
	_back_button.visible = index > 0 and not last
	if step.enter.is_valid():
		step.enter.call()
	_focus_step.call_deferred()


func _focus_step() -> void:
	var target: Control = _steps[_index].focus.call()
	if target != null and target.is_inside_tree():
		target.grab_focus()


func _focus_next_button() -> void:
	_update_next_button()
	if not _next_button.disabled:
		_next_button.grab_focus()


func _build_steps() -> void:
	_steps.append(_welcome_step())
	_steps.append(_network_step())
	_steps.append(_pin_step())
	_steps.append(_timezone_step())
	_steps.append(_quota_step())
	_steps.append(_choice_step("Shared quota", "Should video and games share one daily quota?", "_shared_quota", [[true, "Yes, share it"], [false, "No, video only"]]))
	_steps.append(_overrun_step())
	_steps.append(_game_window_step())
	_steps.append(_bedtime_step())
	_steps.append(_choice_step("Overrun at bedtime", "Can a film finish after bedtime, within the overrun allowance?", "_bedtime_overrun", [[true, "Yes"], [false, "No, stop at bedtime"]]))
	_steps.append(_usb_step())
	_steps.append(_finish_step())


# ---- Pages ----

func _text_page(lines: Array[String]) -> VBoxContainer:
	var page := VBoxContainer.new()
	page.add_theme_constant_override("separation", 24)
	for line in lines:
		page.add_child(UiTheme.muted_label(line, UiTheme.FONT_SIZE))
	return page


func _welcome_step() -> Step:
	var page := _text_page([
		"Hello! This sets up da-box for your family.",
		"Use the arrow keys or the controller to move. Enter or A picks. Esc or B goes back.",
		"You can change all of these settings later in the admin app on your phone.",
	])
	var step := Step.new("Welcome to da-box", page, func() -> bool: return true, func() -> Control: return _next_button)
	return step


func _network_step() -> Step:
	var page := VBoxContainer.new()
	page.add_theme_constant_override("separation", 24)
	_network_status = UiTheme.muted_label("Checking the network…", UiTheme.FONT_SIZE)
	page.add_child(_network_status)
	_wifi_button = Button.new()
	_wifi_button.text = "Choose a Wi-Fi network"
	_wifi_button.size_flags_horizontal = Control.SIZE_SHRINK_BEGIN
	_wifi_button.pressed.connect(_scan_wifi)
	page.add_child(_wifi_button)
	_wifi_list = VBoxContainer.new()
	_wifi_list.add_theme_constant_override("separation", 12)
	page.add_child(_wifi_list)
	_wifi_prompt = UiTheme.muted_label("")
	page.add_child(_wifi_prompt)
	_wifi_keyboard = OnScreenKeyboard.new()
	_wifi_keyboard.visible = false
	_wifi_keyboard.submitted.connect(_connect_wifi)
	page.add_child(_wifi_keyboard)

	var step := Step.new("Network", page, func() -> bool: return _network_connected, _network_focus)
	step.enter = _refresh_network
	step.back = func() -> bool:
		if _wifi_keyboard.visible or _wifi_list.get_child_count() > 0:
			_close_wifi_picker()
			return true
		return false
	return step


func _network_focus() -> Control:
	if _wifi_keyboard.visible:
		return _wifi_keyboard.first_button()
	if _network_connected:
		return _next_button
	return _wifi_button if _wifi_button.visible else _back_button


func _refresh_network() -> void:
	var reply := await Api.service_get("/box/setup/network")
	if not reply.ok:
		_network_status.text = "The network status could not load."
		return
	var status: Dictionary = reply.data
	var connection: String = status["connection_type"]
	_network_connected = connection != "none"
	var address: String = status["ip_address"] if status["ip_address"] is String else ""
	var descriptions := {
		"ethernet": "Connected with a cable. IP address: %s" % address,
		"wifi": "Connected to Wi-Fi. IP address: %s" % address,
		"none": "Not connected. Plug in a network cable, or choose a Wi-Fi network.",
	}
	_network_status.text = descriptions.get(connection, "")
	_wifi_button.visible = status["wifi_available"]
	if _index == 1 and _network_connected:
		_focus_next_button()


func _scan_wifi() -> void:
	_wifi_prompt.text = "Looking for Wi-Fi networks…"
	var reply := await Api.service_get("/box/setup/wifi")
	_clear_children(_wifi_list)
	if not reply.ok or reply.data.is_empty():
		_wifi_prompt.text = "No Wi-Fi networks found."
		return
	_wifi_prompt.text = "Pick your network:"
	for network in reply.data:
		var button := Button.new()
		button.text = "%s   (%d%%)" % [network["ssid"], network["signal"]]
		button.alignment = HORIZONTAL_ALIGNMENT_LEFT
		button.pressed.connect(_choose_wifi.bind(network["ssid"], network["secure"]))
		_wifi_list.add_child(button)
	(_wifi_list.get_child(0) as Button).grab_focus()


func _choose_wifi(ssid: String, secure: bool) -> void:
	_wifi_ssid = ssid
	_clear_children(_wifi_list)
	if not secure:
		_connect_wifi("")
		return
	_wifi_prompt.text = "Type the password for %s, then pick Done:" % ssid
	_wifi_keyboard.text = ""
	_wifi_keyboard.visible = true
	_wifi_keyboard.first_button().grab_focus()


func _connect_wifi(password: String) -> void:
	_wifi_prompt.text = "Connecting to %s…" % _wifi_ssid
	var reply := await Api.service_post("/box/setup/wifi", {"ssid": _wifi_ssid, "password": password})
	var connected: bool = reply.ok and reply.data["connected"]
	if connected:
		_close_wifi_picker()
		_wifi_prompt.text = "Connected to %s." % _wifi_ssid
		await _refresh_network()
	else:
		var reason: String = reply.data["message"] if reply.ok else "No reply from the box."
		_wifi_prompt.text = "Could not connect: %s. Try again." % reason


func _close_wifi_picker() -> void:
	_clear_children(_wifi_list)
	_wifi_keyboard.visible = false
	_wifi_prompt.text = ""
	_wifi_button.grab_focus()


func _pin_step() -> Step:
	var page := VBoxContainer.new()
	page.add_theme_constant_override("separation", 16)
	_pin_message = UiTheme.muted_label("", UiTheme.FONT_SIZE)
	_pin_message.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	page.add_child(_pin_message)
	_pin_pad = PinPad.new()
	_pin_pad.submitted.connect(_on_pin_submitted)
	page.add_child(_pin_pad)
	_reset_pin_entry("Choose a PIN for the admin app: 4 to 8 numbers.")

	var step := Step.new("Admin PIN", page, func() -> bool: return not _pin.is_empty(), func() -> Control: return _pin_pad.first_button())
	step.back = func() -> bool:
		if not _pin_first.is_empty() and _pin.is_empty():
			_reset_pin_entry("Choose a PIN for the admin app: 4 to 8 numbers.")
			return true
		return false
	return step


func _reset_pin_entry(message: String) -> void:
	_pin = ""
	_pin_first = ""
	_pin_message.text = message
	_pin_pad.clear()


func _on_pin_submitted(entered: String) -> void:
	if _pin_first.is_empty():
		_pin_first = entered
		_pin_pad.clear()
		_pin_message.text = "Enter the same PIN again."
	elif entered == _pin_first:
		_pin = entered
		_pin_message.text = "PIN saved."
		_next()
	else:
		_reset_pin_entry("The two PINs were not the same. Choose a PIN again.")


func _timezone_step() -> Step:
	var page := VBoxContainer.new()
	page.add_theme_constant_override("separation", 16)
	_timezone_label = UiTheme.muted_label("Pick your region.", UiTheme.FONT_SIZE)
	page.add_child(_timezone_label)
	var scroll := ScrollContainer.new()
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	scroll.follow_focus = true
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	var padding := MarginContainer.new()
	padding.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	for side in ["left", "right", "top", "bottom"]:
		padding.add_theme_constant_override("margin_" + side, 12)
	_timezone_grid = GridContainer.new()
	_timezone_grid.columns = 4
	_timezone_grid.add_theme_constant_override("h_separation", 16)
	_timezone_grid.add_theme_constant_override("v_separation", 16)
	padding.add_child(_timezone_grid)
	scroll.add_child(padding)
	page.add_child(scroll)

	var step := Step.new("Time zone", page, func() -> bool: return not _timezone.is_empty(), _timezone_focus)
	step.enter = _load_timezones
	step.back = func() -> bool:
		if _timezone_grid.has_meta("region"):
			_show_regions()
			return true
		return false
	return step


func _timezone_focus() -> Control:
	return _timezone_grid.get_child(0) as Control if _timezone_grid.get_child_count() > 0 else _back_button


func _load_timezones() -> void:
	if _timezones.is_empty():
		var reply := await Api.service_get("/box/setup/timezones")
		if not reply.ok:
			_timezone_label.text = "The time zones could not load."
			return
		_timezones = PackedStringArray(reply.data)
	_show_regions()


func _show_regions() -> void:
	_timezone_grid.remove_meta("region")
	_clear_children(_timezone_grid)
	var regions: Array[String] = []
	for zone in _timezones:
		var region := zone.get_slice("/", 0)
		if not regions.has(region):
			regions.append(region)
	for region in regions:
		_timezone_grid.add_child(_grid_button(region.replace("_", " "), _show_cities.bind(region)))
	_timezone_label.text = "Time zone: %s. Pick your region." % _timezone if not _timezone.is_empty() else "Pick your region."
	_focus_step.call_deferred()


func _show_cities(region: String) -> void:
	_timezone_grid.set_meta("region", region)
	_clear_children(_timezone_grid)
	for zone in _timezones:
		if zone.begins_with(region + "/"):
			var city := zone.trim_prefix(region + "/").replace("_", " ").replace("/", " / ")
			_timezone_grid.add_child(_grid_button(city, _choose_timezone.bind(zone)))
	_timezone_label.text = "Pick the city nearest to you."
	_focus_step.call_deferred()


func _choose_timezone(zone: String) -> void:
	_timezone = zone
	_timezone_label.text = "Time zone: %s" % zone
	_focus_next_button()


func _quota_step() -> Step:
	_quota = ValuePicker.new(ValuePicker.Format.MINUTES, 15, 720, 15, 60)
	var page := _picker_page(
		"How much video time per day? With a shared quota, this also covers games.",
		_quota)
	return Step.new("Daily quota", page, func() -> bool: return _quota.has_value(), func() -> Control: return _quota)


func _overrun_step() -> Step:
	_overrun = ValuePicker.new(ValuePicker.Format.MINUTES, 0, 120, 5, 20)
	var page := _picker_page(
		"A film can start only if it ends before the quota runs out plus this many minutes.",
		_overrun)
	return Step.new("Overrun allowance", page, func() -> bool: return _overrun.has_value(), func() -> Control: return _overrun)


func _picker_page(question: String, picker: ValuePicker) -> VBoxContainer:
	picker.editing_finished.connect(_focus_next_button)
	var page := VBoxContainer.new()
	page.add_theme_constant_override("separation", 30)
	page.add_child(UiTheme.muted_label(question, UiTheme.FONT_SIZE))
	picker.size_flags_horizontal = Control.SIZE_SHRINK_BEGIN
	page.add_child(picker)
	page.add_child(UiTheme.muted_label("Press Enter, then Up and Down to change the value. Press Enter again when it is right."))
	return page


func _choice_step(title: String, question: String, field: String, options: Array) -> Step:
	var row := ChoiceRow.new(options, 420)
	row.changed.connect(func(_value: Variant) -> void: _focus_next_button())
	set(field, row)
	var page := VBoxContainer.new()
	page.add_theme_constant_override("separation", 30)
	page.add_child(UiTheme.muted_label(question, UiTheme.FONT_SIZE))
	page.add_child(row)
	return Step.new(title, page, func() -> bool: return row.has_value(), func() -> Control: return row.first_button())


func _game_window_step() -> Step:
	var page := VBoxContainer.new()
	page.add_theme_constant_override("separation", 16)
	page.add_child(UiTheme.muted_label("For each day, can games be played, and when? Enter on a time, then Up and Down."))
	var copy_button := _copy_monday_button(_copy_monday_games)
	page.add_child(copy_button)

	var grid := GridContainer.new()
	grid.columns = 4
	grid.add_theme_constant_override("h_separation", 24)
	grid.add_theme_constant_override("v_separation", 10)
	for day in DAYS:
		var label := Label.new()
		label.text = day[1]
		label.custom_minimum_size.x = 240
		grid.add_child(label)
		var choice := ChoiceRow.new([[true, "Games"], [false, "No games"]], 220, 72)
		grid.add_child(choice)
		var from_picker := _time_picker(16 * 60)
		var to_picker := _time_picker(18 * 60)
		from_picker.custom_minimum_size = Vector2(200, 72)
		to_picker.custom_minimum_size = Vector2(200, 72)
		grid.add_child(from_picker)
		grid.add_child(to_picker)
		choice.changed.connect(func(games: Variant) -> void:
			from_picker.disabled = not games
			to_picker.disabled = not games
			from_picker.focus_mode = Control.FOCUS_ALL if games else Control.FOCUS_NONE
			to_picker.focus_mode = Control.FOCUS_ALL if games else Control.FOCUS_NONE)
		_game_rows[day[0]] = {"choice": choice, "from": from_picker, "to": to_picker}
	page.add_child(_scrolling(grid))
	_game_message = UiTheme.muted_label("")
	page.add_child(_game_message)
	return Step.new("Game window", page, _game_windows_ready, func() -> Control: return copy_button)


func _game_windows_ready() -> bool:
	var problems: Array[String] = []
	for day in DAYS:
		var row: Dictionary = _game_rows[day[0]]
		var choice: ChoiceRow = row["choice"]
		if not choice.has_value():
			problems.append(day[1])
		elif choice.value:
			var from_picker: ValuePicker = row["from"]
			var to_picker: ValuePicker = row["to"]
			if not from_picker.has_value() or not to_picker.has_value() or to_picker.value <= from_picker.value:
				problems.append(day[1])
	_game_message.text = "" if problems.is_empty() else "Still to set: %s. The end time must be after the start time." % ", ".join(problems)
	return problems.is_empty()


func _copy_monday_games() -> void:
	var monday: Dictionary = _game_rows["mon"]
	var monday_choice: ChoiceRow = monday["choice"]
	if not monday_choice.has_value():
		return
	for day in DAYS:
		var row: Dictionary = _game_rows[day[0]]
		(row["choice"] as ChoiceRow).select(monday_choice.value)
		(row["from"] as ValuePicker).set_value((monday["from"] as ValuePicker).value)
		(row["to"] as ValuePicker).set_value((monday["to"] as ValuePicker).value)


func _bedtime_step() -> Step:
	var page := VBoxContainer.new()
	page.add_theme_constant_override("separation", 16)
	page.add_child(UiTheme.muted_label("At bedtime the box stops and shuts down. Set it for each day."))
	var copy_button := _copy_monday_button(_copy_monday_bedtime)
	page.add_child(copy_button)
	var grid := GridContainer.new()
	grid.columns = 2
	grid.add_theme_constant_override("h_separation", 24)
	grid.add_theme_constant_override("v_separation", 10)
	for day in DAYS:
		var label := Label.new()
		label.text = day[1]
		label.custom_minimum_size.x = 240
		grid.add_child(label)
		var picker := _time_picker(19 * 60)
		picker.custom_minimum_size = Vector2(200, 72)
		grid.add_child(picker)
		_bedtimes[day[0]] = picker
	page.add_child(_scrolling(grid))
	var all_set := func() -> bool:
		for day in DAYS:
			if not (_bedtimes[day[0]] as ValuePicker).has_value():
				return false
		return true
	return Step.new("Bedtime", page, all_set, func() -> Control: return copy_button)


func _copy_monday_bedtime() -> void:
	var monday: ValuePicker = _bedtimes["mon"]
	for day in DAYS:
		(_bedtimes[day[0]] as ValuePicker).set_value(monday.value)


func _usb_step() -> Step:
	_usb_playback = ChoiceRow.new([[true, "On"], [false, "Off"]], 220)
	_usb_games = ChoiceRow.new([[true, "On"], [false, "Off"]], 220)
	var page := VBoxContainer.new()
	page.add_theme_constant_override("separation", 30)
	page.add_child(UiTheme.muted_label("Can children play films and music from a USB stick?", UiTheme.FONT_SIZE))
	page.add_child(_usb_playback)
	page.add_child(UiTheme.muted_label("Can children play games from a USB stick?", UiTheme.FONT_SIZE))
	page.add_child(_usb_games)
	_usb_games.changed.connect(func(_value: Variant) -> void: _focus_next_button())
	var both_set := func() -> bool: return _usb_playback.has_value() and _usb_games.has_value()
	return Step.new("USB sticks", page, both_set, func() -> Control: return _usb_playback.first_button())


func _finish_step() -> Step:
	_finish_page = VBoxContainer.new()
	_finish_page.add_theme_constant_override("separation", 24)
	var step := Step.new("All done?", _finish_page, func() -> bool: return true, _finish_focus)
	step.enter = _show_summary
	step.back = func() -> bool:
		if _finish_page.has_meta("saved"):
			return true
		_show_step(_index - 1)
		return true
	return step


func _finish_focus() -> Control:
	for child in _finish_page.get_children():
		if child is Button:
			return child
	return null


func _show_summary() -> void:
	_clear_children(_finish_page)
	var lines: Array[String] = [
		"Time zone: %s" % _timezone,
		"Daily quota: %s (%s)" % [ValuePicker.format_minutes(_quota.value), "shared with games" if _shared_quota.value else "video only"],
		"Overrun allowance: %s%s" % [ValuePicker.format_minutes(_overrun.value), ", also at bedtime" if _bedtime_overrun.value else ""],
		"USB: media %s, games %s" % ["on" if _usb_playback.value else "off", "on" if _usb_games.value else "off"],
	]
	for line in lines:
		_finish_page.add_child(UiTheme.muted_label(line, UiTheme.FONT_SIZE))
	var finish := Button.new()
	finish.text = "Finish setup"
	finish.custom_minimum_size = Vector2(360, 96)
	finish.add_theme_stylebox_override("normal", UiTheme.rounded_box(UiTheme.GOOD.darkened(0.3), 24))
	finish.pressed.connect(_submit)
	_finish_page.add_child(finish)
	var back := Button.new()
	back.text = "Go back and change"
	back.custom_minimum_size = Vector2(360, 96)
	back.pressed.connect(func() -> void: _show_step(_index - 1))
	_finish_page.add_child(back)


func _submit() -> void:
	var game_windows := {}
	var bedtimes := {}
	for day in DAYS:
		var row: Dictionary = _game_rows[day[0]]
		var games: bool = (row["choice"] as ChoiceRow).value
		game_windows[day[0]] = {
			"start": ValuePicker.format_time((row["from"] as ValuePicker).value),
			"end": ValuePicker.format_time((row["to"] as ValuePicker).value),
		} if games else null
		bedtimes[day[0]] = ValuePicker.format_time((_bedtimes[day[0]] as ValuePicker).value)
	var payload := {
		"pin": _pin,
		"timezone": _timezone,
		"limits": {
			"daily_quota_minutes": _quota.value,
			"shared_quota": _shared_quota.value,
			"overrun_minutes": _overrun.value,
			"game_windows": game_windows,
			"bedtimes": bedtimes,
			"bedtime_overrun": _bedtime_overrun.value,
			"usb_playback": _usb_playback.value,
			"usb_games": _usb_games.value,
		},
	}
	var reply := await Api.service_post("/box/setup/complete", payload)
	if not reply.ok:
		_finish_page.add_child(UiTheme.muted_label("The setup could not be saved (error %d). Check the values and try again." % reply.status))
		return
	await Api.refresh_state()
	_show_admin_link(reply.data["admin_urls"])


func _show_admin_link(urls: Array) -> void:
	_finish_page.set_meta("saved", true)
	_clear_children(_finish_page)
	_title_label.text = "Setup is done!"
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 60)
	var qr := TextureRect.new()
	qr.custom_minimum_size = Vector2(380, 380)
	qr.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	qr.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT
	qr.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
	row.add_child(qr)
	var text := VBoxContainer.new()
	text.add_theme_constant_override("separation", 20)
	text.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	text.add_child(UiTheme.muted_label("To open the admin app, scan the code with your phone, or type one of these addresses. Your phone must be on the same Wi-Fi.", UiTheme.FONT_SIZE))
	for url in urls:
		text.add_child(UiTheme.title_label(url))
	var start := Button.new()
	start.text = "Start using da-box"
	start.custom_minimum_size = Vector2(420, 96)
	start.size_flags_horizontal = Control.SIZE_SHRINK_BEGIN
	start.pressed.connect(func() -> void: finished.emit())
	text.add_child(start)
	row.add_child(text)
	_finish_page.add_child(row)
	start.grab_focus.call_deferred()
	Api.clear_texture_cache()
	qr.texture = await Api.texture("/box/admin-qr.png")


# ---- Helpers ----

func _scrolling(content: Control) -> ScrollContainer:
	var scroll := ScrollContainer.new()
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	scroll.follow_focus = true
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	var padding := MarginContainer.new()
	padding.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	for side in ["left", "right", "top", "bottom"]:
		padding.add_theme_constant_override("margin_" + side, 8)
	padding.add_child(content)
	scroll.add_child(padding)
	return scroll


func _time_picker(first_value: int) -> ValuePicker:
	return ValuePicker.new(ValuePicker.Format.TIME_OF_DAY, 0, MINUTES_PER_DAY - TIME_STEP, TIME_STEP, first_value)


func _copy_monday_button(action: Callable) -> Button:
	var button := Button.new()
	button.text = "Copy Monday to every day"
	button.size_flags_horizontal = Control.SIZE_SHRINK_BEGIN
	button.pressed.connect(action)
	return button


func _grid_button(text: String, action: Callable) -> Button:
	var button := Button.new()
	button.text = text
	button.custom_minimum_size = Vector2(380, 80)
	button.clip_text = true
	button.pressed.connect(action)
	return button


static func _clear_children(node: Node) -> void:
	for child in node.get_children():
		node.remove_child(child)
		child.queue_free()
