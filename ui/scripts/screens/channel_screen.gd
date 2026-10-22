class_name ChannelScreen
extends Screen
## Watches (or listens to) one channel live. Up and Down change the channel.
## Video plays in the mpv window above this screen; music plays with this screen showing.
## When nothing is on, it shows "Back soon!" until the next programme starts.

const POLL_SECONDS := 0.5
const NOTHING_ON_POLL_SECONDS := 5.0
# mpv may need a moment to start. Do not treat "idle" as the end before this.
const START_GRACE_SECONDS := 3.0

var _channel_id: String
var _channel_order: Array[String]
var _now: Dictionary = {}
var _playing := false
var _started_at := 0.0
var _seen_playing := false
var _busy := false
var _next_check := 0.0

var _channel_label: Label
var _title: Label
var _subtitle: Label
var _art: TextureRect
var _hint: Label


func _init(channel_id: String, channel_order: Array[String]) -> void:
	_channel_id = channel_id
	_channel_order = channel_order


func _ready() -> void:
	super()
	var row := HBoxContainer.new()
	row.alignment = BoxContainer.ALIGNMENT_CENTER
	row.add_theme_constant_override("separation", 60)
	_art = TextureRect.new()
	_art.custom_minimum_size = Vector2(420, 420)
	_art.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	_art.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_COVERED
	_art.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	row.add_child(_art)

	var text := VBoxContainer.new()
	text.alignment = BoxContainer.ALIGNMENT_CENTER
	text.custom_minimum_size.x = 900
	text.add_theme_constant_override("separation", 20)
	_channel_label = UiTheme.muted_label("", UiTheme.FONT_SIZE)
	text.add_child(_channel_label)
	_title = UiTheme.title_label("")
	_title.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	text.add_child(_title)
	_subtitle = UiTheme.muted_label("", UiTheme.FONT_SIZE)
	text.add_child(_subtitle)
	_hint = UiTheme.muted_label("Up / Down: change channel   ·   B or Esc: back to the guide")
	text.add_child(_hint)
	row.add_child(text)
	page_margin(row)

	var timer := Timer.new()
	timer.wait_time = POLL_SECONDS
	timer.autostart = true
	timer.timeout.connect(_poll)
	add_child(timer)
	_tune()


func go_back() -> void:
	_playing = false
	await Api.agent_post("/control", {"action": "stop"})
	close_screen.emit()


func _unhandled_input(event: InputEvent) -> void:
	if event.is_action_pressed("ui_up"):
		_change_channel(-1)
	elif event.is_action_pressed("ui_down"):
		_change_channel(1)
	else:
		return
	get_viewport().set_input_as_handled()


func _change_channel(step: int) -> void:
	if _channel_order.size() < 2 or _busy:
		return
	var index := (_channel_order.find(_channel_id) + step + _channel_order.size()) % _channel_order.size()
	_channel_id = _channel_order[index]
	_tune()


## Finds what is on now and plays it from the right point.
func _tune() -> void:
	_busy = true
	_playing = false
	var reply := await Api.service_get("/box/channels/%s/now" % _channel_id)
	_busy = false
	if not reply.ok:
		_show_text("", "This channel could not load.", "")
		return
	_now = reply.data
	_channel_label.text = "Channel %d  ·  %s" % [_channel_order.find(_channel_id) + 1, _now["channel_name"]]
	var slot: Variant = _now["slot"]
	if slot == null:
		await Api.agent_post("/control", {"action": "stop"})
		_show_nothing_on()
		return
	_show_text(slot["title"], slot["subtitle"] if slot["subtitle"] is String else "", slot["art_url"] if slot["art_url"] is String else "")
	var kind := "audio" if _now["kind"] == "music" else "video"
	var play := await Api.agent_post("/play", {
		"kind": kind,
		"mode": "channel",
		"start_seconds": _now["offset_seconds"],
		"items": [{"path": _now["path"], "title": slot["title"]}],
	})
	if not play.ok:
		_show_text("", "This programme would not play.", "")
		return
	_playing = true
	_seen_playing = false
	_started_at = Time.get_ticks_msec() / 1000.0


func _show_nothing_on() -> void:
	var upcoming: Variant = _now["next"]
	var when := ""
	if upcoming != null:
		when = "Next: %s at %s" % [upcoming["title"], String(upcoming["start"]).substr(11, 5)]
	_show_text("Back soon!", when, "")
	_next_check = Time.get_ticks_msec() / 1000.0 + NOTHING_ON_POLL_SECONDS


func _show_text(title: String, subtitle: String, art_url: String) -> void:
	_title.text = title
	_subtitle.text = subtitle
	_art.texture = null
	_art.visible = not art_url.is_empty()
	if not art_url.is_empty():
		_load_art(art_url)


func _load_art(art_url: String) -> void:
	var loaded := await Api.texture(art_url)
	if is_instance_valid(_art):
		_art.texture = loaded


func _poll() -> void:
	if _busy:
		return
	var now := Time.get_ticks_msec() / 1000.0
	if not _playing:
		if _now.get("slot") == null and now >= _next_check:
			_tune()
		return
	var reply := await Api.agent_get("/status")
	if not reply.ok or not _playing:
		return
	var status: Dictionary = reply.data
	for request in status.get("requests", []):
		_change_channel(-1 if request == "channel-up" else 1)
		return
	if status["state"] != "idle":
		_seen_playing = true
		return
	if not _seen_playing and now - _started_at < START_GRACE_SECONDS:
		return
	if _programme_should_have_ended():
		_tune()
	else:
		# Esc in the mpv window stopped it early: back to the guide.
		_playing = false
		close_screen.emit()


func _programme_should_have_ended() -> bool:
	var slot: Variant = _now.get("slot")
	if slot == null:
		return true
	var watched := Time.get_ticks_msec() / 1000.0 - _started_at
	var remaining := Time.get_unix_time_from_datetime_string(slot["end"]) - Time.get_unix_time_from_datetime_string(_now["now"]) - watched
	return remaining < 5.0
