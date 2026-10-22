class_name BigTile
extends Button
## A large coloured tile with an icon, a name and an optional line under it (Home screen).

var _subtitle: Label


func _init(title: String, icon_kind: Icon.Kind, colour: Color, subtitle: String = "") -> void:
	name = title + "Tile"
	custom_minimum_size = Vector2(380, 460)
	focus_mode = Control.FOCUS_ALL
	add_theme_stylebox_override("normal", UiTheme.rounded_box(colour, 48))
	add_theme_stylebox_override("hover", UiTheme.rounded_box(colour.lightened(0.1), 48))
	add_theme_stylebox_override("pressed", UiTheme.rounded_box(colour.darkened(0.1), 48))
	add_theme_stylebox_override("disabled", UiTheme.rounded_box(colour.darkened(0.6), 48))
	add_theme_stylebox_override("focus", UiTheme.focus_ring(54))

	var column := VBoxContainer.new()
	column.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	column.alignment = BoxContainer.ALIGNMENT_CENTER
	column.mouse_filter = Control.MOUSE_FILTER_IGNORE
	column.add_theme_constant_override("separation", 16)
	add_child(column)

	var picture := Icon.new(icon_kind, UiTheme.TEXT, 180)
	picture.size_flags_horizontal = Control.SIZE_SHRINK_CENTER
	column.add_child(picture)

	var name_label := Label.new()
	name_label.text = title
	name_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	name_label.add_theme_font_size_override("font_size", 60)
	name_label.add_theme_font_override("font", UiTheme.font(650))
	column.add_child(name_label)

	_subtitle = Label.new()
	_subtitle.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	_subtitle.add_theme_font_size_override("font_size", UiTheme.SMALL_FONT_SIZE)
	column.add_child(_subtitle)
	set_subtitle(subtitle)

	FocusPop.attach(self)


func set_subtitle(text: String) -> void:
	_subtitle.text = text
	_subtitle.visible = not text.is_empty()
