extends Node
## Soft sounds when the child moves, picks and goes back. The parent can turn them off.

var _move := AudioStreamPlayer.new()
var _select := AudioStreamPlayer.new()
var _back := AudioStreamPlayer.new()


func _ready() -> void:
	process_mode = Node.PROCESS_MODE_ALWAYS
	for pair in [[_move, "move"], [_select, "select"], [_back, "back"]]:
		var player: AudioStreamPlayer = pair[0]
		player.stream = load("res://sounds/%s.wav" % pair[1])
		add_child(player)
	get_viewport().gui_focus_changed.connect(func(_control: Control) -> void: _play(_move))


func _input(event: InputEvent) -> void:
	if event.is_action_pressed("ui_accept"):
		_play(_select)
	elif event.is_action_pressed("ui_cancel"):
		_play(_back)


func _play(player: AudioStreamPlayer) -> void:
	var appearance: Dictionary = Api.state.get("appearance", {})
	if appearance.get("sounds", true):
		player.play()
