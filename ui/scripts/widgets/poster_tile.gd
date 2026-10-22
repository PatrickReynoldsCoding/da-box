class_name PosterTile
extends Button
## A film poster or album cover with its name under it.

const POSTER_SIZE := Vector2(300, 450)
const SQUARE_SIZE := Vector2(340, 340)

var _art: TextureRect
var _placeholder: Control


func _init(title: String, subtitle: String, art_path: String, colour: Color, square: bool = false, badge: String = "", placeholder: Icon.Kind = Icon.Kind.FILM) -> void:
	var art_size := SQUARE_SIZE if square else POSTER_SIZE
	custom_minimum_size = art_size + Vector2(0, 110)
	focus_mode = Control.FOCUS_ALL
	add_theme_stylebox_override("normal", StyleBoxEmpty.new())
	add_theme_stylebox_override("hover", StyleBoxEmpty.new())
	add_theme_stylebox_override("pressed", StyleBoxEmpty.new())
	add_theme_stylebox_override("focus", UiTheme.focus_ring(28))

	var column := VBoxContainer.new()
	column.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	column.mouse_filter = Control.MOUSE_FILTER_IGNORE
	add_child(column)

	var frame := Panel.new()
	frame.custom_minimum_size = art_size
	frame.clip_children = CanvasItem.CLIP_CHILDREN_ONLY
	frame.add_theme_stylebox_override("panel", UiTheme.rounded_box(colour, 24))
	frame.mouse_filter = Control.MOUSE_FILTER_IGNORE
	column.add_child(frame)

	_placeholder = Icon.new(Icon.Kind.MUSIC if square and placeholder == Icon.Kind.FILM else placeholder, Color(1, 1, 1, 0.6), 160)
	_placeholder.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	frame.add_child(_placeholder)

	_art = TextureRect.new()
	_art.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	_art.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	_art.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_COVERED
	_art.mouse_filter = Control.MOUSE_FILTER_IGNORE
	frame.add_child(_art)

	if not badge.is_empty():
		var badge_label := Label.new()
		badge_label.text = badge
		badge_label.add_theme_font_size_override("font_size", 24)
		badge_label.add_theme_color_override("font_color", UiTheme.BACKGROUND_TOP)
		badge_label.add_theme_stylebox_override("normal", UiTheme.rounded_box(UiTheme.WARNING, 12, 8))
		badge_label.position = Vector2(12, 12)
		frame.add_child(badge_label)

	var title_label := Label.new()
	title_label.text = title
	title_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	title_label.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
	title_label.custom_minimum_size.x = art_size.x
	column.add_child(title_label)

	if not subtitle.is_empty():
		var subtitle_label := UiTheme.muted_label(subtitle, 26)
		subtitle_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		subtitle_label.autowrap_mode = TextServer.AUTOWRAP_OFF
		subtitle_label.text_overrun_behavior = TextServer.OVERRUN_TRIM_ELLIPSIS
		column.add_child(subtitle_label)

	FocusPop.attach(self)
	if not art_path.is_empty():
		_load_art(art_path)


## "USB", "Hidden", both, or nothing, for a film or album from the box API.
static func badge_text(item: Dictionary) -> String:
	var parts: Array[String] = []
	if item.get("source") == "usb":
		parts.append("USB")
	if item.get("hidden", false):
		parts.append("Hidden")
	return " · ".join(parts)


## Greyed out: still focusable (so the child can see why), but faded.
func set_unavailable(unavailable: bool) -> void:
	modulate = Color(1, 1, 1, 0.35) if unavailable else Color.WHITE


func _load_art(art_path: String) -> void:
	var loaded := await Api.texture(art_path)
	if loaded != null and is_instance_valid(_art):
		_art.texture = loaded
		_placeholder.visible = false
