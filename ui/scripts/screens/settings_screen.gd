class_name SettingsScreen
extends Screen
## Box settings that anyone may use (no parent mode): Update da-box, Posters and info, About.
## It opens from the small Settings button on Home, out of the kids' way, and Update asks
## "Are you sure?" with No focused first (DESIGN_CORRECTIONS_2.md, part 7).
## The box restarts this UI near the end of an update, so after that Home shows again.

const POLL_SECONDS := 2.0
const LOG_LINES := 6

var _back_button: Button
var _version: Label
var _status: Label
var _log: Label
var _update_buttons: HBoxContainer
var _check_button: Button
var _update_button: Button
var _confirm_row: HBoxContainer
var _confirm_no: Button
var _admin_qr: TextureRect
var _admin_urls: VBoxContainer
var _about_version: Label
var _timer: Timer
var _latest := ""
var _accounts: VBoxContainer
var _posters_status: Label
var _phone_panel: HBoxContainer
var _phone_qr: TextureRect
var _lookup_button: Button
var _lookup_confirm: HBoxContainer
var _lookup_no: Button
var _posters_timer: Timer


func _ready() -> void:
	super()
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 28)
	var top := header("Settings", UiTheme.WARNING)
	_back_button = Button.new()
	_back_button.text = "Back"
	_back_button.custom_minimum_size = Vector2(240, 80)
	_back_button.size_flags_horizontal = Control.SIZE_EXPAND | Control.SIZE_SHRINK_END
	_back_button.pressed.connect(go_back)
	top.add_child(_back_button)
	column.add_child(top)

	var scroll := ScrollContainer.new()
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	scroll.follow_focus = true
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	var sections := VBoxContainer.new()
	sections.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	sections.add_theme_constant_override("separation", 56)
	sections.add_child(_make_update_section())
	sections.add_child(_make_posters_section())
	sections.add_child(_make_about_section())
	scroll.add_child(sections)
	column.add_child(scroll)
	# Posters and info and About are text only: Down scrolls to them.
	key_scroll = scroll
	page_margin(column)

	_timer = Timer.new()
	_timer.wait_time = POLL_SECONDS
	_timer.timeout.connect(_refresh)
	add_child(_timer)
	_posters_timer = Timer.new()
	_posters_timer.wait_time = 5.0
	_posters_timer.timeout.connect(refresh_posters)
	add_child(_posters_timer)
	_check()
	refresh_posters()
	_show_about()


func default_focus() -> Control:
	return _back_button


func go_back() -> void:
	# Esc or B on "Are you sure?" means No, not leaving the screen.
	if _confirm_row.visible:
		_cancel_update()
		return
	if _lookup_confirm.visible:
		_cancel_lookup()
		return
	super()


func on_shown() -> void:
	# Back from typing a key: show whether it works.
	refresh_posters()


# ---- Update da-box ----

func _make_update_section() -> VBoxContainer:
	var section := _section("Update da-box")
	_version = UiTheme.title_label("")
	_version.add_theme_font_size_override("font_size", 44)
	section.add_child(_version)
	_status = UiTheme.muted_label("Checking for updates…", UiTheme.FONT_SIZE)
	_status.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	section.add_child(_status)

	_update_buttons = HBoxContainer.new()
	_update_buttons.add_theme_constant_override("separation", 30)
	_check_button = Button.new()
	_check_button.text = "Check again"
	_check_button.custom_minimum_size = Vector2(300, 90)
	_check_button.pressed.connect(_check)
	_update_buttons.add_child(_check_button)
	_update_button = Button.new()
	_update_button.custom_minimum_size = Vector2(420, 90)
	_update_button.visible = false
	_update_button.pressed.connect(_ask_to_update)
	_update_buttons.add_child(_update_button)
	section.add_child(_update_buttons)

	_confirm_row = HBoxContainer.new()
	_confirm_row.add_theme_constant_override("separation", 30)
	_confirm_row.visible = false
	var question := UiTheme.muted_label("Are you sure? What is playing stops, and the TV restarts at the end.", UiTheme.FONT_SIZE)
	question.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	question.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_confirm_row.add_child(question)
	_confirm_no = Button.new()
	_confirm_no.text = "No"
	_confirm_no.custom_minimum_size = Vector2(200, 90)
	_confirm_no.pressed.connect(_cancel_update)
	_confirm_row.add_child(_confirm_no)
	var confirm_yes := Button.new()
	confirm_yes.text = "Yes, update"
	confirm_yes.custom_minimum_size = Vector2(280, 90)
	confirm_yes.pressed.connect(_start)
	_confirm_row.add_child(confirm_yes)
	section.add_child(_confirm_row)

	_log = UiTheme.muted_label("")
	_log.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_log.visible = false
	section.add_child(_log)
	return section


func _check() -> void:
	_status.text = "Checking for updates…"
	_show(await Api.service_post("/box/software/check"))


func _refresh() -> void:
	_show(await Api.service_get("/box/software"))


func _ask_to_update() -> void:
	_update_buttons.visible = false
	_confirm_row.visible = true
	_confirm_no.grab_focus()


func _cancel_update() -> void:
	_confirm_row.visible = false
	_update_buttons.visible = true
	_update_button.grab_focus()


func _start() -> void:
	_confirm_row.visible = false
	_update_buttons.visible = true
	_update_button.visible = false
	_back_button.grab_focus()
	_status.text = "Starting the update…"
	_show(await Api.service_post("/box/software/update"))


## Shows a reply from the service. While the update restarts the service, there is no reply: keep asking.
func _show(reply: Variant) -> void:
	if not is_inside_tree():
		return
	if not reply.ok:
		_status.text = Api.error_text(reply, "The box service is not answering. Wait a moment.")
		if reply.status == 0 or reply.status >= 500:
			_timer.start()
		return
	var status: Dictionary = reply.data
	var running: bool = status.get("running", false)
	var latest: Variant = status.get("latest")
	_latest = latest if latest is String else ""
	_version.text = "Installed: %s" % status.get("installed", "unknown")
	if not _latest.is_empty():
		_version.text += "  ·  Newest: %s" % _latest
	_about_version.text = "da-box %s" % status.get("installed", "unknown")
	var check_error: Variant = status.get("check_error")
	if running:
		_status.text = "Updating… this can take some minutes. The TV goes dark for a moment at the end, then Home shows again."
	elif check_error is String:
		_status.text = check_error
	elif status.get("available", false):
		_status.text = "A new version is ready."
	else:
		_status.text = "da-box is up to date."
	var last_result: Variant = status.get("last_result")
	if not running and last_result is String:
		_status.text += "  Last update: %s" % last_result
	var log_lines: Array = status.get("log", [])
	_log.text = "\n".join(log_lines.slice(maxi(0, log_lines.size() - LOG_LINES)))
	_log.visible = not log_lines.is_empty()
	var can_update: bool = status.get("available", false) and not running
	if not can_update and (_update_button.has_focus() or _confirm_row.visible):
		_confirm_row.visible = false
		_update_buttons.visible = true
		_back_button.grab_focus()
	_update_button.visible = can_update
	_update_button.text = "Update to %s" % _latest if not _latest.is_empty() else "Update"
	_check_button.disabled = running
	if running:
		_timer.start()
	else:
		_timer.stop()


# ---- Posters and info (DESIGN_CORRECTIONS_2.md, part 4) ----

const ACCOUNT_STATES := {
	"not_needed": "No key needed", "not_set": "Not set", "working": "Working", "not_working": "Not working",
}


func _make_posters_section() -> VBoxContainer:
	var section := _section("Posters and info")
	var intro := UiTheme.muted_label(
		"The box looks up posters, covers, box art and short details on the internet, by each item's name.", UiTheme.FONT_SIZE)
	intro.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	section.add_child(intro)
	_accounts = VBoxContainer.new()
	_accounts.add_theme_constant_override("separation", 8)
	section.add_child(_accounts)

	var buttons := HBoxContainer.new()
	buttons.add_theme_constant_override("separation", 30)
	buttons.add_child(_settings_button("Enter TMDB key", _enter_tmdb_key, 340))
	buttons.add_child(_settings_button("ScreenScraper account", _enter_screenscraper, 420))
	buttons.add_child(_settings_button("Use a phone", _toggle_phone, 280))
	section.add_child(buttons)

	_phone_panel = HBoxContainer.new()
	_phone_panel.add_theme_constant_override("separation", 40)
	_phone_panel.visible = false
	_phone_qr = TextureRect.new()
	_phone_qr.custom_minimum_size = Vector2(240, 240)
	_phone_qr.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	_phone_qr.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT
	_phone_qr.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
	_phone_panel.add_child(_phone_qr)
	var phone_hint := UiTheme.muted_label(
		"Scan this with a phone on the same Wi-Fi. It opens the admin app's key form, where you can paste the keys. This screen updates when they are saved.",
		UiTheme.FONT_SIZE)
	phone_hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	phone_hint.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_phone_panel.add_child(phone_hint)
	section.add_child(_phone_panel)

	_posters_status = UiTheme.muted_label("", UiTheme.FONT_SIZE)
	_posters_status.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	section.add_child(_posters_status)
	_lookup_button = _settings_button("Look up now", _ask_to_look_up, 320)
	_lookup_button.size_flags_horizontal = Control.SIZE_SHRINK_BEGIN
	section.add_child(_lookup_button)
	_lookup_confirm = HBoxContainer.new()
	_lookup_confirm.add_theme_constant_override("separation", 30)
	_lookup_confirm.visible = false
	var question := UiTheme.muted_label("Look up everything that has no posters and info yet?", UiTheme.FONT_SIZE)
	question.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	question.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_lookup_confirm.add_child(question)
	_lookup_no = _settings_button("No", _cancel_lookup, 200)
	_lookup_confirm.add_child(_lookup_no)
	_lookup_confirm.add_child(_settings_button("Yes, look up", _look_up, 300))
	section.add_child(_lookup_confirm)
	return section


func _settings_button(text: String, action: Callable, width: float) -> Button:
	var button := Button.new()
	button.text = text
	button.custom_minimum_size = Vector2(width, 90)
	button.pressed.connect(action)
	return button


func refresh_posters() -> void:
	var reply := await Api.service_get("/box/posters")
	if reply.ok and is_inside_tree():
		show_posters(reply.data)


## Fills the section from the service's status (also used by the key tests).
func show_posters(status: Dictionary) -> void:
	for child in _accounts.get_children():
		child.queue_free()
	for account in status["accounts"]:
		var state: String = ACCOUNT_STATES.get(account["state"], account["state"])
		if account.get("reason") is String:
			state += ": " + String(account["reason"])
		var row := UiTheme.muted_label("%s  ·  %s  ·  %s" % [account["name"], account["used_for"], state], UiTheme.FONT_SIZE)
		row.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		if account["state"] == "working":
			row.add_theme_color_override("font_color", UiTheme.GOOD)
		elif account["state"] == "not_working":
			row.add_theme_color_override("font_color", UiTheme.WARNING)
		_accounts.add_child(row)
	var parts: Array[String] = ["%d have posters and info" % status["done"]]
	if status["waiting"] > 0:
		parts.append("%d to look up" % status["waiting"])
	if status["no_account"] > 0:
		parts.append("%d wait for a TMDB key" % status["no_account"])
	if status["not_found"] > 0:
		parts.append("%d not found" % status["not_found"])
	if status["failed"] > 0:
		parts.append("%d failed" % status["failed"])
	var text := ", ".join(parts) + "."
	if status.get("last_error") is String:
		text += "\nLast problem: " + String(status["last_error"])
	_posters_status.text = text
	# Keep the numbers moving while the box looks things up.
	if status["waiting"] > 0:
		_posters_timer.start()
	else:
		_posters_timer.stop()


func _save_accounts(fields: Dictionary) -> void:
	_posters_status.text = "Checking the key…"
	var reply := await Api.service_put("/box/posters/accounts", fields)
	if is_inside_tree():
		if reply.ok:
			show_posters(reply.data)
		else:
			_posters_status.text = Api.error_text(reply, "The key could not be saved.")


func _enter_tmdb_key() -> void:
	var entry := TextEntryScreen.new("TMDB key",
		"Get a free API key at themoviedb.org (Settings, API). Typing it is slow: \"Use a phone\" lets you paste it instead.")
	entry.entered.connect(func(text: String) -> void:
		if not text.is_empty():
			_save_accounts({"tmdb_api_key": text}))
	open_screen.emit(entry)


## Four fields, one after the other: user name, password, developer id, developer password.
func _enter_screenscraper() -> void:
	var steps := [
		["screenscraper_user", "ScreenScraper user name", "Your account on screenscraper.fr. Optional: without it, games get box art only.", false],
		["screenscraper_password", "ScreenScraper password", "", true],
		["screenscraper_dev_id", "ScreenScraper developer id", "ScreenScraper's API also needs a developer id and password. Ask for them (free) on the ScreenScraper forum.", false],
		["screenscraper_dev_password", "ScreenScraper developer password", "", true],
	]
	_next_screenscraper_step(steps, 0, {})


func _next_screenscraper_step(steps: Array, index: int, fields: Dictionary) -> void:
	if index >= steps.size():
		_save_accounts(fields)
		return
	var step: Array = steps[index]
	var entry := TextEntryScreen.new(step[1], step[2], "", step[3])
	entry.entered.connect(func(text: String) -> void:
		if text.is_empty():
			return
		fields[step[0]] = text
		# The next field opens once this one has closed.
		_next_screenscraper_step.call_deferred(steps, index + 1, fields))
	open_screen.emit(entry)


func _toggle_phone() -> void:
	_phone_panel.visible = not _phone_panel.visible
	if _phone_panel.visible and _phone_qr.texture == null:
		var qr := await Api.texture("/box/admin-qr.png?target=accounts")
		if is_instance_valid(_phone_qr):
			_phone_qr.texture = qr
	if _phone_panel.visible:
		_posters_timer.start()


func _ask_to_look_up() -> void:
	_lookup_button.visible = false
	_lookup_confirm.visible = true
	_lookup_no.grab_focus()


func _cancel_lookup() -> void:
	_lookup_confirm.visible = false
	_lookup_button.visible = true
	_lookup_button.grab_focus()


func _look_up() -> void:
	_cancel_lookup()
	var reply := await Api.service_post("/box/posters/lookup")
	if reply.ok and is_inside_tree():
		show_posters(reply.data)


# ---- About ----

func _make_about_section() -> VBoxContainer:
	var section := _section("About")
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 48)
	_admin_qr = TextureRect.new()
	_admin_qr.custom_minimum_size = Vector2(260, 260)
	_admin_qr.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	_admin_qr.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT
	_admin_qr.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST
	row.add_child(_admin_qr)
	var text := VBoxContainer.new()
	text.add_theme_constant_override("separation", 16)
	text.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_about_version = UiTheme.title_label("da-box")
	_about_version.add_theme_font_size_override("font_size", 44)
	text.add_child(_about_version)
	var hint := UiTheme.muted_label("Admin app: scan the code with a phone on the same Wi-Fi, or type", UiTheme.FONT_SIZE)
	hint.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	text.add_child(hint)
	_admin_urls = VBoxContainer.new()
	text.add_child(_admin_urls)
	row.add_child(text)
	section.add_child(row)
	return section


func _show_about() -> void:
	for url: String in Api.state.get("admin_urls", []):
		var label := UiTheme.title_label(url)
		label.add_theme_font_size_override("font_size", 40)
		_admin_urls.add_child(label)
	var qr := await Api.texture("/box/admin-qr.png")
	if is_instance_valid(_admin_qr):
		_admin_qr.texture = qr


func _section(title: String) -> VBoxContainer:
	var section := VBoxContainer.new()
	section.add_theme_constant_override("separation", 20)
	var label := UiTheme.title_label(title)
	label.add_theme_font_size_override("font_size", 48)
	label.add_theme_color_override("font_color", UiTheme.WARNING)
	section.add_child(label)
	return section
