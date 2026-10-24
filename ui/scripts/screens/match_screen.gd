class_name MatchScreen
extends Screen
## Parent mode: fix a video's, group's or album's posters and info (DESIGN_CORRECTIONS_2.md,
## 4.1 item 6). The box searches by the name; pick the right result, or change the search.

var _item_id: String
var _search_text: String
var _search_button: Button
var _results: VBoxContainer
var _message: Label


func _init(item_id: String, title: String) -> void:
	_item_id = item_id
	_search_text = title


func _ready() -> void:
	super()
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 24)
	column.add_child(header("Posters and info", UiTheme.WARNING))
	_search_button = Button.new()
	_search_button.alignment = HORIZONTAL_ALIGNMENT_LEFT
	_search_button.custom_minimum_size.y = 90
	_search_button.pressed.connect(_change_search)
	column.add_child(_search_button)
	_message = UiTheme.muted_label("", UiTheme.FONT_SIZE)
	_message.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	column.add_child(_message)
	var scroll := ScrollContainer.new()
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	scroll.follow_focus = true
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	_results = VBoxContainer.new()
	_results.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_results.add_theme_constant_override("separation", 14)
	scroll.add_child(_results)
	column.add_child(scroll)
	page_margin(column)
	search()


func default_focus() -> Control:
	return _results.get_child(0) as Control if _results.get_child_count() > 0 else _search_button


func search() -> void:
	_search_button.text = "Search: %s   (change)" % _search_text
	_message.text = "Searching…"
	var reply := await Api.service_post("/box/content/%s/metadata/search" % _item_id, {"title": _search_text})
	if not is_inside_tree():
		return
	if not reply.ok:
		show_results([])
		_message.text = Api.error_text(reply, "The search did not work. Check Settings, Posters and info.")
		return
	show_results(reply.data)


## The search results as buttons (also used by the key tests).
func show_results(candidates: Array) -> void:
	for child in _results.get_children():
		# Out of the list now, so the focus does not stay on a button that is going away.
		_results.remove_child(child)
		child.queue_free()
	_message.text = "Pick the right one." if not candidates.is_empty() else "Nothing found. Change the search."
	for candidate in candidates:
		var button := Button.new()
		var year := " (%d)" % int(candidate["year"]) if candidate.get("year") != null else ""
		var detail: Variant = candidate.get("description") if candidate.get("description") != null else candidate.get("artist")
		button.text = "%s%s%s" % [candidate["title"], year, ("   —   %s" % detail) if detail is String else ""]
		button.alignment = HORIZONTAL_ALIGNMENT_LEFT
		button.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
		button.clip_text = true
		button.custom_minimum_size.y = 90
		button.pressed.connect(_apply.bind(candidate))
		_results.add_child(button)
	var target := default_focus()
	if is_inside_tree() and target != null:
		target.grab_focus.call_deferred()


func _change_search() -> void:
	var entry := TextEntryScreen.new("Search for", "", _search_text, false, 60)
	entry.entered.connect(func(text: String) -> void:
		if not text.is_empty():
			_search_text = text
			search())
	open_screen.emit(entry)


func _apply(candidate: Dictionary) -> void:
	_message.text = "Saving…"
	var reply := await Api.service_post("/box/content/%s/metadata/apply" % _item_id, candidate)
	if not is_inside_tree():
		return
	if reply.ok:
		Api.clear_texture_cache()
		close_screen.emit()
	else:
		_message.text = Api.error_text(reply, "That could not be saved.")
