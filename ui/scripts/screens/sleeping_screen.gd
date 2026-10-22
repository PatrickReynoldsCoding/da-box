class_name SleepingScreen
extends Screen
## "That's all the TV for today!" or "It's bedtime", with a countdown to the shut-down.

var _countdown: Label
var _title: Label


func _ready() -> void:
	super()
	var column := VBoxContainer.new()
	column.alignment = BoxContainer.ALIGNMENT_CENTER
	column.add_theme_constant_override("separation", 40)
	var moon := Icon.new(Icon.Kind.TV, UiTheme.TEXT_MUTED, 220)
	moon.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	column.add_child(moon)
	_title = UiTheme.title_label("")
	_title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	column.add_child(_title)
	_countdown = UiTheme.muted_label("", UiTheme.FONT_SIZE)
	_countdown.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	column.add_child(_countdown)
	page_margin(column)
	var timer := Timer.new()
	timer.wait_time = 1.0
	timer.autostart = true
	timer.timeout.connect(_refresh)
	add_child(timer)
	_refresh()


func go_back() -> void:
	pass


func _refresh() -> void:
	var limits := Api.limits
	_title.text = limits.get("video_locked_reason", "Time to rest!") if limits.get("video_locked_reason") is String else "Time to rest!"
	var shutdown_at: Variant = limits.get("shutdown_at")
	if shutdown_at is String:
		var left := Api.wall_seconds(shutdown_at) - Api.wall_seconds(limits["now"])
		_countdown.text = "The TV is going to sleep. See you tomorrow!" if left <= 0 else "The TV turns off in %d seconds." % int(left)
