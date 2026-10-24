class_name SoftwareScreen
extends Screen
## Parent mode: update da-box itself to the newest GitHub release. The box restarts this UI
## near the end of an update, so after that Home shows again.

const POLL_SECONDS := 2.0

var _version: Label
var _status: Label
var _log: Label
var _back_button: Button
var _check_button: Button
var _update_button: Button
var _timer: Timer


func _ready() -> void:
	super()
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 28)
	column.add_child(header("Update da-box", UiTheme.WARNING))
	_version = UiTheme.title_label("")
	_version.add_theme_font_size_override("font_size", 44)
	column.add_child(_version)
	_status = UiTheme.muted_label("Checking for updates…", UiTheme.FONT_SIZE)
	_status.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	column.add_child(_status)
	var buttons := HBoxContainer.new()
	buttons.add_theme_constant_override("separation", 30)
	_back_button = Button.new()
	_back_button.text = "Back"
	_back_button.custom_minimum_size = Vector2(240, 90)
	_back_button.pressed.connect(go_back)
	buttons.add_child(_back_button)
	_check_button = Button.new()
	_check_button.text = "Check again"
	_check_button.custom_minimum_size = Vector2(300, 90)
	_check_button.pressed.connect(_check)
	buttons.add_child(_check_button)
	_update_button = Button.new()
	_update_button.custom_minimum_size = Vector2(420, 90)
	_update_button.visible = false
	_update_button.pressed.connect(_start)
	buttons.add_child(_update_button)
	column.add_child(buttons)
	_log = UiTheme.muted_label("")
	_log.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	_log.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_log.clip_text = true
	column.add_child(_log)
	page_margin(column)

	_timer = Timer.new()
	_timer.wait_time = POLL_SECONDS
	_timer.timeout.connect(_refresh)
	add_child(_timer)
	_check()


func default_focus() -> Control:
	return _back_button


func _check() -> void:
	_status.text = "Checking for updates…"
	_show(await Api.service_post("/box/software/check"))


func _refresh() -> void:
	_show(await Api.service_get("/box/software"))


func _start() -> void:
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
	_version.text = "Installed: %s" % status.get("installed", "unknown")
	if latest is String:
		_version.text += "  ·  Newest: %s" % latest
	var check_error: Variant = status.get("check_error")
	if running:
		_status.text = "Updating… this can take some minutes. The TV goes dark for a moment at the end, then Home shows again."
	elif check_error is String:
		_status.text = check_error
	elif status.get("available", false):
		_status.text = "A new version is ready. What is playing stops while the box updates."
	else:
		_status.text = "da-box is up to date."
	var last_result: Variant = status.get("last_result")
	if not running and last_result is String:
		_status.text += "  Last update: %s" % last_result
	var log_lines: Array = status.get("log", [])
	_log.text = "\n".join(log_lines.slice(maxi(0, log_lines.size() - 8)))
	var can_update: bool = status.get("available", false) and not running
	if not can_update and _update_button.has_focus():
		_back_button.grab_focus()
	_update_button.visible = can_update
	_update_button.text = "Update to %s" % latest if latest is String else "Update"
	_check_button.disabled = running
	if running:
		_timer.start()
	else:
		_timer.stop()
