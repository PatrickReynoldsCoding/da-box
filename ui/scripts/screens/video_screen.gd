class_name VideoScreen
extends Screen
## Sits under the mpv window while a video plays. The keyboard goes to mpv;
## the game controller comes here, so this screen sends its buttons to the agent.

const POLL_SECONDS := 0.5
# mpv may need a moment to start. Do not close before this.
const START_GRACE_SECONDS := 3.0

var _title: String
var _started_at := 0.0
var _seen_playing := false
var _stopped := false
## Called with true when the video played to its end, false when it was stopped (a group plays its next video).
var _on_end: Callable


func _init(title: String, on_end: Callable = Callable()) -> void:
	_title = title
	_on_end = on_end


func _ready() -> void:
	super()
	var column := VBoxContainer.new()
	column.alignment = BoxContainer.ALIGNMENT_CENTER
	column.add_theme_constant_override("separation", 30)
	var showing := UiTheme.muted_label("Now showing", UiTheme.FONT_SIZE)
	showing.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	column.add_child(showing)
	var title := UiTheme.title_label(_title)
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	column.add_child(title)
	var hint := UiTheme.muted_label("A or Enter: pause   ·   Left / Right: skip   ·   B or Esc: stop")
	hint.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	column.add_child(hint)
	page_margin(column)

	_started_at = Time.get_ticks_msec() / 1000.0
	var timer := Timer.new()
	timer.wait_time = POLL_SECONDS
	timer.autostart = true
	timer.timeout.connect(_poll)
	add_child(timer)


func go_back() -> void:
	_stopped = true
	Api.agent_post("/control", {"action": "stop"})


func _unhandled_input(event: InputEvent) -> void:
	var actions := {"ui_accept": "pause", "ui_left": "seek_back", "ui_right": "seek_forward"}
	for action in actions:
		if event.is_action_pressed(action):
			Api.agent_post("/control", {"action": actions[action]})
			get_viewport().set_input_as_handled()
			return


func _poll() -> void:
	var reply := await Api.agent_get("/status")
	if not reply.ok:
		return
	var idle: bool = reply.data["state"] == "idle"
	if not idle:
		_seen_playing = true
	var waited := Time.get_ticks_msec() / 1000.0 - _started_at
	if idle and (_seen_playing or waited > START_GRACE_SECONDS):
		var ended := _seen_playing and not _stopped
		close_screen.emit()
		if _on_end.is_valid():
			_on_end.call(ended)
