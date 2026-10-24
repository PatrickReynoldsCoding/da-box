class_name CopyUsbScreen
extends Screen
## Copy from USB (parent mode only): the folders on the drive with tick boxes. Tick a whole
## folder (Films, TV, Music, Games), or open it (Right, then Enter) and tick single items.
## Copy checks the space on the box first. Items already on the box cannot be ticked.

var copy_button: Button
var rows: VBoxContainer
var _sticks: Array = []
var _stick: Dictionary = {}
var _stick_picker: ChoiceRow
var _stick_holder: HBoxContainer
var _summary: Label
var _message: Label
var _ticked: Dictionary = {}
## Folder key -> {"box": TickBox, "open": Button, "items": [item Dictionary], "rows": [Control]}
var _folders: Dictionary = {}
var _item_boxes: Dictionary = {}
var _copy_started := false


func _ready() -> void:
	super()
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 20)
	column.add_child(header("Copy from USB", UiTheme.WARNING))
	_stick_holder = HBoxContainer.new()
	_stick_holder.visible = false
	column.add_child(_stick_holder)
	column.add_child(UiTheme.muted_label("Tick a folder to copy all of it, or open it to tick single items. Items already on the box are skipped."))
	var scroll := ScrollContainer.new()
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	scroll.follow_focus = true
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	rows = VBoxContainer.new()
	rows.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	rows.add_theme_constant_override("separation", 10)
	scroll.add_child(rows)
	column.add_child(scroll)
	var bottom := HBoxContainer.new()
	bottom.add_theme_constant_override("separation", 30)
	copy_button = Button.new()
	copy_button.text = "Copy"
	copy_button.custom_minimum_size = Vector2(300, 90)
	copy_button.add_theme_stylebox_override("normal", UiTheme.rounded_box(UiTheme.GOOD.darkened(0.3), 24))
	copy_button.pressed.connect(_copy)
	bottom.add_child(copy_button)
	_summary = UiTheme.muted_label("", UiTheme.FONT_SIZE)
	_summary.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	bottom.add_child(_summary)
	column.add_child(bottom)
	_message = UiTheme.muted_label("", UiTheme.FONT_SIZE)
	_message.add_theme_color_override("font_color", UiTheme.WARNING)
	column.add_child(_message)
	page_margin(column)
	_refresh_summary()
	_load()


func default_focus() -> Control:
	if not _folders.is_empty():
		var first: Dictionary = _folders.values()[0]
		var box: TickBox = first["box"]
		return box if box.focus_mode != Control.FOCUS_NONE else first["open"]
	return copy_button if copy_button.focus_mode != Control.FOCUS_NONE else null


func on_shown() -> void:
	# Back from the progress screen: the copy is running, so go on to Home.
	if _copy_started:
		close_screen.emit.call_deferred()


func _load() -> void:
	var reply := await Api.service_get("/box/usb/tree")
	if not reply.ok:
		_message.text = Api.error_text(reply, "The USB drive could not be read.")
		return
	show_sticks(reply.data)


func show_sticks(sticks: Array) -> void:
	_sticks = sticks
	for child in _stick_holder.get_children():
		child.queue_free()
	_stick_holder.visible = sticks.size() > 1
	if sticks.size() > 1:
		var options := []
		for index in sticks.size():
			options.append([index, sticks[index]["label"]])
		_stick_picker = ChoiceRow.new(options, 300, 80)
		_stick_picker.changed.connect(func(index: Variant) -> void: show_stick(_sticks[index]))
		_stick_holder.add_child(_stick_picker)
	if sticks.is_empty():
		_clear_rows()
		rows.add_child(empty_message("Plug in a USB drive with Films, TV, Music or Games folders."))
		_refresh_summary()
		return
	if _stick_picker != null:
		_stick_picker.select(0)
	else:
		show_stick(sticks[0])


func show_stick(stick: Dictionary) -> void:
	_stick = stick
	_clear_rows()
	if stick["folders"].is_empty():
		rows.add_child(empty_message("No Films, TV, Music or Games folders on \"%s\"." % stick["label"]))
	for folder in stick["folders"]:
		_add_folder(folder)
	_refresh_summary()
	var target := default_focus()
	if target != null and is_inside_tree():
		target.grab_focus.call_deferred()


func _clear_rows() -> void:
	for child in rows.get_children():
		rows.remove_child(child)
		child.queue_free()
	_ticked.clear()
	_folders.clear()
	_item_boxes.clear()


func _add_folder(folder: Dictionary) -> void:
	var key: String = folder["key"]
	var items: Array = folder["items"]
	var to_copy := items.filter(func(item: Dictionary) -> bool: return not item["on_box"])
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 16)
	var label := "%s   ·   all on the box" % folder["name"]
	if not to_copy.is_empty():
		label = "%s   ·   %d to copy   ·   %s" % [folder["name"], to_copy.size(), Api.size_text(folder["bytes"])]
	var box := TickBox.new(label)
	box.name = "Folder-" + key
	box.add_theme_font_size_override("font_size", 40)
	box.disabled = to_copy.is_empty()
	box.focus_mode = Control.FOCUS_NONE if box.disabled else Control.FOCUS_ALL
	box.toggled.connect(_tick_folder.bind(key))
	row.add_child(box)
	var open := Button.new()
	open.text = "Open"
	open.custom_minimum_size = Vector2(200, 84)
	open.pressed.connect(_toggle_open.bind(key))
	row.add_child(open)
	rows.add_child(row)
	# Godot's nearest-neighbour search would pick an item row (wider, just below), so Left
	# and Right stay in the folder's row.
	box.focus_neighbor_right = box.get_path_to(open)
	box.focus_neighbor_left = box.get_path_to(box)
	open.focus_neighbor_left = open.get_path_to(box)
	open.focus_neighbor_right = open.get_path_to(open)

	var item_rows: Array[Control] = []
	for item in items:
		var item_row := HBoxContainer.new()
		var indent := Control.new()
		indent.custom_minimum_size.x = 80
		item_row.add_child(indent)
		var subtitle: String = ("  —  " + String(item["subtitle"])) if item["subtitle"] is String else ""
		var size_text := "On the box" if item["on_box"] else Api.size_text(item["bytes"])
		var item_box := TickBox.new("%s%s   ·   %s" % [item["title"], subtitle, size_text])
		item_box.disabled = item["on_box"]
		item_box.focus_mode = Control.FOCUS_NONE if item_box.disabled else Control.FOCUS_ALL
		item_box.toggled.connect(_tick_item.bind(item["id"], key))
		item_row.add_child(item_box)
		item_row.visible = false
		rows.add_child(item_row)
		item_box.focus_neighbor_left = item_box.get_path_to(item_box)
		item_box.focus_neighbor_right = item_box.get_path_to(item_box)
		item_rows.append(item_row)
		_item_boxes[item["id"]] = item_box
	_folders[key] = {"box": box, "open": open, "items": to_copy, "rows": item_rows}


func is_open(key: String) -> bool:
	return _folders[key]["open"].text == "Close"


func _toggle_open(key: String) -> void:
	var folder: Dictionary = _folders[key]
	var opening := not is_open(key)
	folder["open"].text = "Close" if opening else "Open"
	for item_row in folder["rows"]:
		item_row.visible = opening


func _tick_folder(ticked: bool, key: String) -> void:
	for item in _folders[key]["items"]:
		_set_ticked(item["id"], ticked)
		(_item_boxes[item["id"]] as TickBox).set_ticked(ticked)
	_refresh_folder(key)
	_refresh_summary()


func _tick_item(ticked: bool, item_id: String, key: String) -> void:
	_set_ticked(item_id, ticked)
	_refresh_folder(key)
	_refresh_summary()


func _set_ticked(item_id: String, ticked: bool) -> void:
	if ticked:
		_ticked[item_id] = true
	else:
		_ticked.erase(item_id)


func _refresh_folder(key: String) -> void:
	var items: Array = _folders[key]["items"]
	var count := items.filter(func(item: Dictionary) -> bool: return _ticked.has(item["id"])).size()
	(_folders[key]["box"] as TickBox).set_ticked(count > 0 and count == items.size(), count > 0)


## The ticked items, in the order of the list.
func ticked_ids() -> Array:
	var found := []
	for key in _folders:
		for item in _folders[key]["items"]:
			if _ticked.has(item["id"]):
				found.append(item["id"])
	return found


func _ticked_bytes() -> float:
	var total := 0.0
	for key in _folders:
		for item in _folders[key]["items"]:
			if _ticked.has(item["id"]):
				total += item["bytes"]
	return total


func _refresh_summary() -> void:
	var count := _ticked.size()
	copy_button.disabled = count == 0
	copy_button.focus_mode = Control.FOCUS_NONE if count == 0 else Control.FOCUS_ALL
	_summary.text = "Nothing ticked yet." if count == 0 else "%d item%s ticked  ·  %s" % [count, "" if count == 1 else "s", Api.size_text(_ticked_bytes())]


func _copy() -> void:
	_message.text = ""
	var request := {"stick_id": _stick["stick_id"], "item_ids": ticked_ids()}
	var check := await Api.service_post("/box/usb/check", request)
	if not check.ok:
		_message.text = Api.error_text(check, "The box could not check the space.")
		return
	if not check.data["fits"]:
		_message.text = "Not enough space on the box. The copy needs %s, and %s is free. Tick fewer things." % [
			Api.size_text(check.data["bytes_needed"]), Api.size_text(check.data["bytes_free"])]
		return
	var reply := await Api.service_post("/box/usb/copy", request)
	if not reply.ok:
		_message.text = Api.error_text(reply, "The copy could not start.")
		return
	_copy_started = true
	Api.copy_progress = reply.data
	Api.copy_changed.emit(reply.data)
	open_screen.emit(CopyProgressScreen.new())
