class_name GuideScreen
extends Screen
## Today's TV guide: channels down the side, time across the top.
## A "Game time" row shows the game window, and a line shows bedtime.

const PIXELS_PER_MINUTE := 8.0
const ROW_HEIGHT := 120.0
const ROW_GAP := 14.0
const HEADER_HEIGHT := 60.0
const NAME_WIDTH := 300.0
const DAY_MINUTES := 24 * 60

var _guide: Dictionary = {}
var _names: VBoxContainer
var _scroll: ScrollContainer
var _timeline: Control
var _message: Label
var _focus_target: Control
var _day_start_unix := 0.0


func _ready() -> void:
	super()
	var column := VBoxContainer.new()
	column.add_theme_constant_override("separation", 24)
	column.add_child(header("TV guide", UiTheme.TV))

	var body := HBoxContainer.new()
	body.size_flags_vertical = Control.SIZE_EXPAND_FILL
	body.add_theme_constant_override("separation", 16)
	_names = VBoxContainer.new()
	_names.custom_minimum_size.x = NAME_WIDTH
	_names.add_theme_constant_override("separation", ROW_GAP)
	body.add_child(_names)

	_scroll = ScrollContainer.new()
	_scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_scroll.follow_focus = true
	_scroll.vertical_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	_timeline = Control.new()
	_scroll.add_child(_timeline)
	body.add_child(_scroll)
	column.add_child(body)

	_message = UiTheme.muted_label("Loading the guide…")
	column.add_child(_message)
	page_margin(column)
	_load()


func default_focus() -> Control:
	return _focus_target


func _load() -> void:
	var reply := await Api.service_get("/box/guide")
	if not reply.ok:
		_message.text = "The guide could not load. Try again soon."
		return
	_guide = reply.data
	var channels: Array = _guide["channels"]
	if channels.is_empty():
		_message.text = "No channels yet. Ask a grown-up to make some in the admin app."
		return
	_message.text = "Pick a programme to watch that channel."
	var now_unix := _unix(_guide["now"])
	_day_start_unix = _unix(_guide["day"] + "T00:00:00")
	var rows := channels.size() + 1
	_timeline.custom_minimum_size = Vector2(DAY_MINUTES * PIXELS_PER_MINUTE, HEADER_HEIGHT + rows * (ROW_HEIGHT + ROW_GAP))

	_add_time_labels()
	_names.add_child(_spacer(HEADER_HEIGHT - ROW_GAP))
	var row := 0
	for channel in channels:
		_names.add_child(_channel_name(channel))
		_add_row(channel, row, now_unix)
		row += 1
	_add_game_row(row)
	_add_vertical_line(_guide.get("bedtime"), UiTheme.FOCUS, "Bedtime")
	_add_vertical_line(_guide["now"], UiTheme.TEXT, "")

	if _focus_target == null:
		_focus_target = _first_button(_timeline)
	# The scroll range is only known after the layout pass.
	await get_tree().process_frame
	await get_tree().process_frame
	# Show from half an hour ago.
	_scroll.scroll_horizontal = int(maxf(0.0, _x_for(now_unix) - 30 * PIXELS_PER_MINUTE))
	if _focus_target != null:
		_focus_target.grab_focus()


func _x_for(unix_time: float) -> float:
	return (unix_time - _day_start_unix) / 60.0 * PIXELS_PER_MINUTE


## Seconds for a box-local time like "2026-10-21T18:30:00+01:00". Godot ignores the
## "+01:00" part, so this is wall-clock time. All guide times use the box's time zone,
## so comparing them this way is correct.
static func _unix(text: Variant) -> float:
	return Time.get_unix_time_from_datetime_string(text)


func _row_y(row: int) -> float:
	return HEADER_HEIGHT + row * (ROW_HEIGHT + ROW_GAP)


func _add_time_labels() -> void:
	for half_hour in DAY_MINUTES / 30:
		var label := UiTheme.muted_label("%02d:%02d" % [half_hour / 2, (half_hour % 2) * 30], 26)
		label.autowrap_mode = TextServer.AUTOWRAP_OFF
		label.position = Vector2(half_hour * 30 * PIXELS_PER_MINUTE + 6, 8)
		_timeline.add_child(label)


func _channel_name(channel: Dictionary) -> Label:
	var label := Label.new()
	label.text = "%d  %s" % [int(channel["number"]), channel["name"]]
	label.custom_minimum_size = Vector2(NAME_WIDTH, ROW_HEIGHT)
	label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	label.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	label.add_theme_font_override("font", UiTheme.font(650))
	return label


func _add_row(channel: Dictionary, row: int, now_unix: float) -> void:
	var colour := UiTheme.MUSIC if channel["kind"] == "music" else UiTheme.TV
	for slot in channel["slots"]:
		var start := _unix(slot["start"])
		var end := _unix(slot["end"])
		# The past is not useful to children, and skipping it keeps the grid light.
		if end < now_unix - 3600:
			continue
		var button := Button.new()
		button.text = slot["title"]
		button.tooltip_text = slot["subtitle"] if slot["subtitle"] is String else ""
		button.clip_text = true
		button.alignment = HORIZONTAL_ALIGNMENT_LEFT
		button.add_theme_font_size_override("font_size", 30)
		var on_now := start <= now_unix and now_unix < end
		var past := end <= now_unix
		var fill := colour.darkened(0.15) if on_now else (Color(1, 1, 1, 0.05) if past else colour.darkened(0.55))
		# Video programmes that cannot finish in the time left today are faded (rule c).
		if channel["kind"] == "video" and not past and not Api.video_fits(end - maxf(start, now_unix)):
			button.modulate = Color(1, 1, 1, 0.35)
		button.add_theme_stylebox_override("normal", UiTheme.rounded_box(fill, 16, 12))
		button.position = Vector2(_x_for(start) + 2, _row_y(row))
		button.size = Vector2(maxf((end - start) / 60.0 * PIXELS_PER_MINUTE - 4, 20), ROW_HEIGHT)
		button.pressed.connect(_watch.bind(channel["id"]))
		_timeline.add_child(button)
		if on_now and _focus_target == null:
			_focus_target = button


func _add_game_row(row: int) -> void:
	_names.add_child(_channel_name({"number": 0, "name": "Game time"}))
	(_names.get_child(_names.get_child_count() - 1) as Label).text = "Game time"
	for window in _guide.get("game_windows", []):
		var start := _unix(window["start"])
		var end := _unix(window["end"])
		var bar := Label.new()
		bar.text = "Games open"
		bar.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
		bar.add_theme_color_override("font_color", UiTheme.BACKGROUND_TOP)
		bar.add_theme_stylebox_override("normal", UiTheme.rounded_box(UiTheme.GAMES, 16, 12))
		bar.position = Vector2(_x_for(start), _row_y(row))
		bar.size = Vector2((end - start) / 60.0 * PIXELS_PER_MINUTE, ROW_HEIGHT)
		_timeline.add_child(bar)


func _add_vertical_line(moment: Variant, colour: Color, caption: String) -> void:
	if not (moment is String):
		return
	var x := _x_for(_unix(moment))
	var line := ColorRect.new()
	line.color = colour
	line.mouse_filter = Control.MOUSE_FILTER_IGNORE
	line.position = Vector2(x - 2, HEADER_HEIGHT - 10)
	line.size = Vector2(4, _timeline.custom_minimum_size.y - HEADER_HEIGHT)
	_timeline.add_child(line)
	if not caption.is_empty():
		var label := Label.new()
		label.text = caption
		label.add_theme_color_override("font_color", colour)
		label.add_theme_font_size_override("font_size", 24)
		label.position = Vector2(x + 8, HEADER_HEIGHT - 34)
		_timeline.add_child(label)


func _watch(channel_id: String) -> void:
	var order: Array[String] = []
	for channel in _guide["channels"]:
		order.append(channel["id"])
	open_screen.emit(ChannelScreen.new(channel_id, order))


func _first_button(node: Node) -> Button:
	for child in node.get_children():
		if child is Button:
			return child
	return null


func _spacer(height: float) -> Control:
	var spacer := Control.new()
	spacer.custom_minimum_size.y = height
	return spacer
