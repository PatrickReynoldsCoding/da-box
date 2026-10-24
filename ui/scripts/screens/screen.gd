class_name Screen
extends Control
## Base for every full-screen page. Main keeps a stack of screens.

signal open_screen(screen: Screen)
signal close_screen

## How far one Down or Up press scrolls `key_scroll` when no control there can take the focus.
const KEY_SCROLL_STEP := 240

## A scroll area with text below or above its last control (Settings). Down scrolls it when
## there is nothing further down to focus, and Up scrolls back to the top before the focus
## moves up out of it, so a controller can read all of it.
var key_scroll: ScrollContainer


func _ready() -> void:
	set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)


func _input(event: InputEvent) -> void:
	if key_scroll == null or not is_visible_in_tree():
		return
	var down := event.is_action_pressed("ui_down", true)
	var up := event.is_action_pressed("ui_up", true)
	if not (down or up):
		return
	var focused := get_viewport().gui_get_focus_owner()
	if focused == null or not key_scroll.is_ancestor_of(focused):
		return
	var bar := key_scroll.get_v_scroll_bar()
	var bottom := bar.max_value - bar.page
	if down and focused.find_valid_focus_neighbor(SIDE_BOTTOM) == null and key_scroll.scroll_vertical < bottom:
		key_scroll.scroll_vertical = mini(key_scroll.scroll_vertical + KEY_SCROLL_STEP, int(bottom))
		get_viewport().set_input_as_handled()
	elif up and key_scroll.scroll_vertical > 0 and (not _shows_in(focused, key_scroll) or _leaves(focused, SIDE_TOP)):
		key_scroll.scroll_vertical = maxi(key_scroll.scroll_vertical - KEY_SCROLL_STEP, 0)
		get_viewport().set_input_as_handled()


## True if moving the focus to that side leaves the scroll area (or there is nowhere to go).
func _leaves(focused: Control, side: Side) -> bool:
	var next := focused.find_valid_focus_neighbor(side)
	return next == null or not key_scroll.is_ancestor_of(next)


## True if the control is fully inside the scroll area's visible part.
static func _shows_in(control: Control, scroll: ScrollContainer) -> bool:
	return scroll.get_global_rect().encloses(control.get_global_rect())


## Called when the screen is shown, also when it shows again after the screen above it closes.
func on_shown() -> void:
	pass


## The control that gets focus when the screen shows.
func default_focus() -> Control:
	return null


## Esc or the B button. The default closes the screen.
func go_back() -> void:
	close_screen.emit()


func page_margin(child: Control) -> MarginContainer:
	var margin := MarginContainer.new()
	margin.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	for side in ["left", "right", "top", "bottom"]:
		margin.add_theme_constant_override("margin_" + side, 80 if side in ["left", "right"] else 60)
	margin.add_child(child)
	add_child(margin)
	return margin


func header(title: String, colour: Color) -> HBoxContainer:
	var row := HBoxContainer.new()
	row.add_theme_constant_override("separation", 24)
	var dot := ColorRect.new()
	dot.color = colour
	dot.custom_minimum_size = Vector2(24, 80)
	row.add_child(dot)
	row.add_child(UiTheme.title_label(title))
	return row


func empty_message(text: String) -> Label:
	var label := UiTheme.muted_label(text, UiTheme.FONT_SIZE)
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	label.size_flags_vertical = Control.SIZE_EXPAND_FILL
	label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	return label


func scrolling_grid(columns: int) -> Array:
	var scroll := ScrollContainer.new()
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	scroll.follow_focus = true
	scroll.horizontal_scroll_mode = ScrollContainer.SCROLL_MODE_DISABLED
	var padding := MarginContainer.new()
	padding.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	# Room for the focus ring and the grow animation at the edges.
	for side in ["left", "right", "top", "bottom"]:
		padding.add_theme_constant_override("margin_" + side, 30)
	scroll.add_child(padding)
	var grid := GridContainer.new()
	grid.columns = columns
	grid.add_theme_constant_override("h_separation", 48)
	grid.add_theme_constant_override("v_separation", 40)
	padding.add_child(grid)
	return [scroll, grid]
