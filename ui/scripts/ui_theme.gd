class_name UiTheme
## Colours, fonts and button styles for the whole box UI.

const BACKGROUND_TOP := Color("1b103d")
const BACKGROUND_BOTTOM := Color("3a1f7a")
const TEXT := Color("fff8e7")
const TEXT_MUTED := Color("c9bdf0")
const FOCUS := Color("ffe14d")
const PANEL := Color(1, 1, 1, 0.08)
const DISABLED := Color(1, 1, 1, 0.25)

const TV := Color("ff5d8f")
const FILMS := Color("ffb703")
const MUSIC := Color("2ec4b6")
const GAMES := Color("8e7dff")
const GOOD := Color("4cd97b")
const WARNING := Color("ff8f40")

const FONT_SIZE := 36
const TITLE_FONT_SIZE := 64
const SMALL_FONT_SIZE := 28


static func font(weight: int = 500) -> Font:
	var base := load("res://fonts/Fredoka.ttf") as FontFile
	var variation := FontVariation.new()
	variation.base_font = base
	variation.variation_opentype = {"wght": weight}
	return variation


static func build() -> Theme:
	var theme := Theme.new()
	theme.default_font = font(500)
	theme.default_font_size = FONT_SIZE

	theme.set_color("font_color", "Label", TEXT)
	for type_name in ["Button", "CheckBox"]:
		theme.set_color("font_color", type_name, TEXT)
		theme.set_color("font_focus_color", type_name, BACKGROUND_TOP)
		theme.set_color("font_hover_color", type_name, TEXT)
		theme.set_color("font_pressed_color", type_name, BACKGROUND_TOP)
		theme.set_color("font_hover_pressed_color", type_name, BACKGROUND_TOP)
		theme.set_color("font_disabled_color", type_name, DISABLED)

	theme.set_stylebox("normal", "Button", rounded_box(PANEL, 24))
	theme.set_stylebox("hover", "Button", rounded_box(Color(1, 1, 1, 0.14), 24))
	theme.set_stylebox("pressed", "Button", rounded_box(FOCUS.darkened(0.1), 24))
	theme.set_stylebox("hover_pressed", "Button", rounded_box(FOCUS.darkened(0.1), 24))
	theme.set_stylebox("disabled", "Button", rounded_box(Color(1, 1, 1, 0.04), 24))
	theme.set_stylebox("focus", "Button", rounded_box(FOCUS, 24, 0))

	theme.set_stylebox("panel", "PanelContainer", rounded_box(PANEL, 32))
	theme.set_stylebox("background", "ProgressBar", rounded_box(Color(1, 1, 1, 0.15), 12))
	theme.set_stylebox("fill", "ProgressBar", rounded_box(MUSIC, 12))
	return theme


static func rounded_box(color: Color, radius: int, padding: int = 20) -> StyleBoxFlat:
	var box := StyleBoxFlat.new()
	box.bg_color = color
	box.set_corner_radius_all(radius)
	box.set_content_margin_all(padding)
	box.anti_aliasing = true
	return box


## A focus style that draws a thick yellow ring instead of filling the button.
static func focus_ring(radius: int) -> StyleBoxFlat:
	var box := StyleBoxFlat.new()
	box.draw_center = false
	box.border_color = FOCUS
	box.set_border_width_all(8)
	box.set_corner_radius_all(radius)
	box.expand_margin_left = 6
	box.expand_margin_right = 6
	box.expand_margin_top = 6
	box.expand_margin_bottom = 6
	return box


static func title_label(text: String) -> Label:
	var label := Label.new()
	label.text = text
	label.add_theme_font_size_override("font_size", TITLE_FONT_SIZE)
	label.add_theme_font_override("font", font(650))
	return label


static func muted_label(text: String, size: int = SMALL_FONT_SIZE) -> Label:
	var label := Label.new()
	label.text = text
	label.add_theme_color_override("font_color", TEXT_MUTED)
	label.add_theme_font_size_override("font_size", size)
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	return label
