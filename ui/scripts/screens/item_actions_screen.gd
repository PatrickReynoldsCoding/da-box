class_name ItemActionsScreen
extends Screen
## Parent mode, one video or game: play it; copy it to the box if it is on a USB stick; and
## for a video, fix its posters and info (DESIGN_CORRECTIONS_2.md, 4.1).

var play_button: Button
var copy_button: Button
var posters_button: Button
var _title: String
var _item_id: String
var _play: Callable
var _on_usb: bool
var _can_match: bool
var _message: Label


func _init(title: String, item_id: String, play: Callable, on_usb: bool = true, can_match: bool = false) -> void:
	_title = title
	_item_id = item_id
	_play = play
	_on_usb = on_usb
	_can_match = can_match


func _ready() -> void:
	super()
	var column := VBoxContainer.new()
	column.alignment = BoxContainer.ALIGNMENT_CENTER
	column.add_theme_constant_override("separation", 40)
	var title := UiTheme.title_label(_title)
	title.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	column.add_child(title)
	var hint := UiTheme.muted_label(
		"This is on a USB stick. Copy it to keep it on the box after the stick comes out." if _on_usb else "Parent mode.",
		UiTheme.FONT_SIZE)
	hint.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	column.add_child(hint)
	var buttons := HBoxContainer.new()
	buttons.alignment = BoxContainer.ALIGNMENT_CENTER
	buttons.add_theme_constant_override("separation", 40)
	play_button = _big_button("Play", _on_play)
	buttons.add_child(play_button)
	copy_button = _big_button("Copy to the box", _on_copy)
	copy_button.visible = _on_usb
	buttons.add_child(copy_button)
	posters_button = _big_button("Posters and info", func() -> void: open_screen.emit(MatchScreen.new(_item_id, _title)))
	posters_button.visible = _can_match
	buttons.add_child(posters_button)
	column.add_child(buttons)
	_message = UiTheme.muted_label("", UiTheme.FONT_SIZE)
	_message.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	column.add_child(_message)
	page_margin(column)


func default_focus() -> Control:
	return play_button


func _big_button(text: String, action: Callable) -> Button:
	var button := Button.new()
	button.text = text
	button.custom_minimum_size = Vector2(440, 120)
	button.add_theme_font_size_override("font_size", 44)
	button.pressed.connect(action)
	FocusPop.attach(button)
	return button


func _on_play() -> void:
	close_screen.emit()
	_play.call()


func _on_copy() -> void:
	var reply := await Api.service_post("/box/content/%s/copy-to-box" % _item_id)
	if not reply.ok:
		_message.text = Api.error_text(reply, "It could not be copied.")
		return
	Api.copy_progress = reply.data
	Api.copy_changed.emit(reply.data)
	close_screen.emit()
	open_screen.emit(CopyProgressScreen.new())
