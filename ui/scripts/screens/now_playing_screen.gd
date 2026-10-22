class_name NowPlayingScreen
extends Screen
## The song that plays now, with big buttons. Back leaves the music playing.

const POLL_SECONDS := 0.5

var _art_url: String
var _cover: TextureRect
var _title: Label
var _artist: Label
var _progress: ProgressBar
var _time: Label
var _pause_icon: Icon
var _pause_button: Button


func _init(art_url: Variant = "") -> void:
	_art_url = art_url if art_url is String else ""


func _ready() -> void:
	super()
	var row := HBoxContainer.new()
	row.alignment = BoxContainer.ALIGNMENT_CENTER
	row.add_theme_constant_override("separation", 80)

	_cover = TextureRect.new()
	_cover.custom_minimum_size = Vector2(620, 620)
	_cover.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	_cover.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_COVERED
	_cover.size_flags_vertical = Control.SIZE_SHRINK_CENTER
	row.add_child(_cover)

	var right := VBoxContainer.new()
	right.alignment = BoxContainer.ALIGNMENT_CENTER
	right.custom_minimum_size.x = 900
	right.add_theme_constant_override("separation", 28)
	right.add_child(UiTheme.muted_label("Now playing", UiTheme.FONT_SIZE))
	_title = UiTheme.title_label("")
	_title.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	right.add_child(_title)
	_artist = UiTheme.muted_label("", UiTheme.FONT_SIZE)
	right.add_child(_artist)
	_progress = ProgressBar.new()
	_progress.show_percentage = false
	_progress.custom_minimum_size.y = 24
	right.add_child(_progress)
	_time = UiTheme.muted_label("")
	right.add_child(_time)

	var controls := HBoxContainer.new()
	controls.add_theme_constant_override("separation", 30)
	controls.add_child(_control_button(Icon.new(Icon.Kind.PREVIOUS, UiTheme.TEXT, 80), "previous"))
	_pause_icon = Icon.new(Icon.Kind.PAUSE, UiTheme.TEXT, 80)
	_pause_button = _control_button(_pause_icon, "pause")
	controls.add_child(_pause_button)
	controls.add_child(_control_button(Icon.new(Icon.Kind.NEXT, UiTheme.TEXT, 80), "next"))
	controls.add_child(_control_button(Icon.new(Icon.Kind.STOP, UiTheme.TEXT, 80), "stop"))
	right.add_child(controls)
	row.add_child(right)
	page_margin(row)

	if not _art_url.is_empty():
		_load_cover()
	var timer := Timer.new()
	timer.wait_time = POLL_SECONDS
	timer.autostart = true
	timer.timeout.connect(_poll)
	add_child(timer)
	_poll()


func default_focus() -> Control:
	return _pause_button


func _control_button(icon_control: Icon, action: String) -> Button:
	var button := Button.new()
	button.custom_minimum_size = Vector2(150, 150)
	button.focus_mode = Control.FOCUS_ALL
	button.add_theme_stylebox_override("focus", UiTheme.focus_ring(24))
	icon_control.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	button.add_child(icon_control)
	button.pressed.connect(func() -> void:
		Api.agent_post("/control", {"action": action})
		_poll())
	FocusPop.attach(button)
	return button


func _load_cover() -> void:
	_cover.texture = await Api.texture(_art_url)


func _poll() -> void:
	var reply := await Api.agent_get("/status")
	if not reply.ok or not is_inside_tree():
		return
	var status: Dictionary = reply.data
	if status["state"] == "idle":
		close_screen.emit()
		return
	_title.text = status["title"] if status["title"] is String else ""
	_artist.text = status["artist"] if status["artist"] is String else ""
	var elapsed: float = status["position_seconds"] if status["position_seconds"] != null else 0.0
	var duration: float = status["duration_seconds"] if status["duration_seconds"] != null else 0.0
	_progress.max_value = maxf(duration, 1.0)
	_progress.value = elapsed
	_time.text = "%s / %s" % [_clock(elapsed), _clock(duration)]
	var paused: bool = status["state"] == "paused"
	_pause_icon.kind = Icon.Kind.PLAY if paused else Icon.Kind.PAUSE
	_pause_icon.queue_redraw()


static func _clock(seconds: float) -> String:
	var whole := int(seconds)
	return "%d:%02d" % [whole / 60, whole % 60]
