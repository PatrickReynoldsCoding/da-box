class_name GameScreen
extends Screen
## Sits under the RetroArch window while a game runs. Closes when the game ends.

const POLL_SECONDS := 1.0
# RetroArch may need a moment to start. Do not close before this.
const START_GRACE_SECONDS := 4.0

var _title: String
var _started_at := 0.0


func _init(title: String) -> void:
	_title = title


func _ready() -> void:
	super()
	var column := VBoxContainer.new()
	column.alignment = BoxContainer.ALIGNMENT_CENTER
	column.add_theme_constant_override("separation", 30)
	var playing := UiTheme.muted_label("Playing", UiTheme.FONT_SIZE)
	playing.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	column.add_child(playing)
	var title := UiTheme.title_label(_title)
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	column.add_child(title)
	var hint := UiTheme.muted_label("To stop: Esc on the keyboard, or Select + Start on the controller. Your game is saved.")
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
	Api.agent_post("/control", {"action": "stop"})


func _poll() -> void:
	var reply := await Api.agent_get("/status")
	if not reply.ok:
		return
	var waited := Time.get_ticks_msec() / 1000.0 - _started_at
	if reply.data["kind"] != "game" and waited > START_GRACE_SECONDS:
		close_screen.emit()
