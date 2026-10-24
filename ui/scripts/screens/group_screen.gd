class_name GroupScreen
extends Screen
## A group: a folder of several videos, played in order (DESIGN_CORRECTIONS_2.md, 2.3).
## "Play" starts after the last video that played to its end; "Play from the start" at the
## first. When a video ends, the next one plays if the limits allow it. In parent mode, a
## group on a USB stick also has "Copy to the box".

var _group_id: String
var _group: Dictionary = {}
var _cover: TextureRect
var _title: Label
var _count: Label
var _videos: VBoxContainer
var _copy_button: Button
var _message: Label
## The first focusable row: Play.
var _play_button: Button


func _init(group_id: String) -> void:
	_group_id = group_id


func _ready() -> void:
	super()
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 80)

	var left := VBoxContainer.new()
	left.add_theme_constant_override("separation", 20)
	_cover = TextureRect.new()
	_cover.custom_minimum_size = Vector2(420, 600)
	_cover.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	_cover.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_COVERED
	left.add_child(_cover)
	_title = UiTheme.title_label("")
	_title.custom_minimum_size.x = 420
	_title.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	left.add_child(_title)
	_count = UiTheme.muted_label("", UiTheme.FONT_SIZE)
	left.add_child(_count)
	_copy_button = Button.new()
	_copy_button.text = "Copy to the box"
	_copy_button.visible = false
	_copy_button.pressed.connect(_copy_to_box)
	left.add_child(_copy_button)
	row.add_child(left)

	var scroll := ScrollContainer.new()
	scroll.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	scroll.follow_focus = true
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	_videos = VBoxContainer.new()
	_videos.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	_videos.add_theme_constant_override("separation", 16)
	scroll.add_child(_videos)
	row.add_child(scroll)

	var column := VBoxContainer.new()
	column.add_child(row)
	row.size_flags_vertical = Control.SIZE_EXPAND_FILL
	_message = UiTheme.muted_label("")
	_message.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	column.add_child(_message)
	page_margin(column)
	_load()


func default_focus() -> Control:
	return _play_button


func _load() -> void:
	var reply := await Api.service_get("/box/groups/" + _group_id)
	if not reply.ok:
		_message.text = "These videos could not load."
		return
	show_group(reply.data)
	if _group["art_url"] is String:
		var cover := await Api.texture(_group["art_url"])
		if is_instance_valid(_cover):
			_cover.texture = cover


## Fills the screen from the service's group (also used by the key tests).
func show_group(group: Dictionary) -> void:
	_group = group
	for child in _videos.get_children():
		child.queue_free()
	_title.text = group["title"]
	var videos: Array = group["videos"]
	_count.text = "%d videos" % videos.size()
	_copy_button.visible = group["source"] == "usb" and Api.parent_mode()
	var resume: int = group["resume_index"]
	var play_text := "Play" if resume == 0 else "Play: %s" % _video_label(videos[resume])
	_play_button = _row_button(play_text, play_from.bind(resume), UiTheme.FILMS)
	_videos.add_child(_play_button)
	if resume > 0:
		_videos.add_child(_row_button("Play from the start", play_from.bind(0), UiTheme.FILMS.darkened(0.25)))
	var section := ""
	for index in videos.size():
		var video: Dictionary = videos[index]
		if video["section"] != section:
			section = video["section"]
			if not section.is_empty():
				var heading := UiTheme.muted_label(section, UiTheme.FONT_SIZE)
				heading.add_theme_color_override("font_color", UiTheme.FILMS)
				_videos.add_child(heading)
		var button := _row_button(_video_label(video), play_from.bind(index), Color(1, 1, 1, 0.08))
		button.set_meta("video_index", index)
		_videos.add_child(button)
	if is_inside_tree():
		_play_button.grab_focus()


static func _video_label(video: Dictionary) -> String:
	var code: Variant = video.get("code")
	return "%s  ·  %s" % [code, video["title"]] if code is String else String(video["title"])


func _row_button(text: String, action: Callable, colour: Color) -> Button:
	var button := Button.new()
	button.text = text
	button.alignment = HORIZONTAL_ALIGNMENT_LEFT
	button.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	button.clip_text = true
	button.custom_minimum_size.y = 90
	button.add_theme_stylebox_override("normal", UiTheme.rounded_box(colour, 20))
	button.pressed.connect(action)
	return button


## Plays one video of the group; when it ends, the next one (if the limits allow it).
func play_from(index: int) -> void:
	var videos: Array = _group.get("videos", [])
	if index < 0 or index >= videos.size():
		return
	var video: Dictionary = videos[index]
	var refusal := await Api.approve_video(VideosScreen.video_seconds(video))
	if not refusal.is_empty():
		_message.text = refusal
		return
	var reply := await Api.agent_post("/play", {"kind": "video", "items": [{"path": video["path"], "title": video["title"]}]})
	if not reply.ok:
		_message.text = "That video would not play."
		return
	_message.text = ""
	open_screen.emit(VideoScreen.new("%s  ·  %s" % [_group["title"], video["title"]], _on_video_end.bind(index)))


func _on_video_end(ended: bool, index: int) -> void:
	if not ended or not is_inside_tree():
		return
	var next := index + 1
	var videos: Array = _group.get("videos", [])
	var resume := next if next < videos.size() else 0
	_group["resume_index"] = resume
	Api.service_post("/box/groups/%s/resume" % _group_id, {"index": resume})
	if next < videos.size():
		play_from(next)
	else:
		show_group(_group)


func _copy_to_box() -> void:
	var reply := await Api.service_post("/box/content/%s/copy-to-box" % _group_id)
	if reply.ok:
		Api.refresh_copy()
		open_screen.emit(CopyProgressScreen.new())
	else:
		_message.text = Api.error_text(reply, "The videos could not be copied.")
