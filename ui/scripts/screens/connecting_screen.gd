class_name ConnectingScreen
extends Screen
## Shows while the box service is starting or cannot be reached.


func _ready() -> void:
	super()
	var column := VBoxContainer.new()
	column.alignment = BoxContainer.ALIGNMENT_CENTER
	column.add_child(_centred(UiTheme.title_label("da-box")))
	column.add_child(_centred(UiTheme.muted_label("Getting ready…", UiTheme.FONT_SIZE)))
	page_margin(column)


func go_back() -> void:
	pass


func _centred(label: Label) -> Label:
	label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	return label
