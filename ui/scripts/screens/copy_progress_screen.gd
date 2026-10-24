class_name CopyProgressScreen
extends Screen
## The Copy from USB job: what it copies now, how far it is, and what it skipped.
## Back leaves the copy running; Home shows a small bar until it ends.

const POLL_SECONDS := 1.0
const LIST_LIMIT := 6

var _title: Label
var _status: Label
var _bar: ProgressBar
var _details: Label
var _back_button: Button
var _stop_button: Button


func _ready() -> void:
	super()
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 28)
	var top := header("Copying from USB", UiTheme.WARNING)
	_title = top.get_child(1) as Label
	column.add_child(top)
	_status = UiTheme.title_label("")
	_status.add_theme_font_size_override("font_size", 44)
	_status.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	column.add_child(_status)
	_bar = ProgressBar.new()
	_bar.show_percentage = false
	_bar.custom_minimum_size.y = 32
	_bar.max_value = 1.0
	column.add_child(_bar)
	_details = UiTheme.muted_label("", UiTheme.FONT_SIZE)
	column.add_child(_details)
	var buttons := HBoxContainer.new()
	buttons.add_theme_constant_override("separation", 30)
	_back_button = Button.new()
	_back_button.custom_minimum_size = Vector2(420, 90)
	_back_button.pressed.connect(go_back)
	buttons.add_child(_back_button)
	_stop_button = Button.new()
	_stop_button.text = "Stop copying"
	_stop_button.custom_minimum_size = Vector2(300, 90)
	_stop_button.pressed.connect(_stop)
	buttons.add_child(_stop_button)
	column.add_child(buttons)
	page_margin(column)

	Api.copy_changed.connect(show_progress)
	show_progress(Api.copy_progress)
	var timer := Timer.new()
	timer.wait_time = POLL_SECONDS
	timer.autostart = true
	timer.timeout.connect(Api.refresh_copy)
	add_child(timer)
	Api.refresh_copy()


func default_focus() -> Control:
	return _back_button


func show_progress(progress: Dictionary) -> void:
	if not is_inside_tree():
		return
	var copying: bool = progress.get("state") == "copying"
	var total := float(progress.get("bytes_total", 0))
	var done := float(progress.get("bytes_done", 0))
	_bar.value = done / total if total > 0 else (0.0 if copying else 1.0)
	_title.text = "Copying from USB" if copying else "Copy from USB"
	if copying:
		var current: Variant = progress.get("current")
		_status.text = ("Now: %s" % current) if current is String else "Scanning the new files…"
	else:
		var message: Variant = progress.get("message")
		_status.text = message if message is String else "No copy is running."
	var lines: Array[String] = []
	if progress.get("items_total", 0) > 0:
		lines.append("%d of %d items  ·  %s of %s" % [
			progress["items_done"], progress["items_total"], Api.size_text(done), Api.size_text(total)])
	if copying:
		lines.append("You can go back and use the box. The copy goes on.")
	lines.append_array(_list_lines("Already on the box", progress.get("skipped", [])))
	lines.append_array(_list_lines("Could not copy", progress.get("errors", [])))
	_details.text = "\n".join(lines)
	_back_button.text = "Back (the copy goes on)" if copying else "Done"
	var can_stop := copying and Api.parent_mode()
	if not can_stop and _stop_button.has_focus():
		_back_button.grab_focus()
	_stop_button.visible = can_stop


static func _list_lines(title: String, names: Array) -> Array[String]:
	if names.is_empty():
		return []
	var shown := names.slice(0, LIST_LIMIT)
	var text := ", ".join(shown)
	if names.size() > LIST_LIMIT:
		text += " and %d more" % (names.size() - LIST_LIMIT)
	return ["%s: %s" % [title, text]]


func _stop() -> void:
	var reply := await Api.service_post("/box/usb/copy/stop")
	if reply.ok:
		show_progress(reply.data)
