class_name FocusPop
## Makes a control grow a little when it gets focus, so children can see where they are.

const FOCUSED_SCALE := Vector2(1.08, 1.08)
const DURATION := 0.12


static func attach(control: Control) -> void:
	control.focus_entered.connect(func() -> void: _animate(control, FOCUSED_SCALE))
	control.focus_exited.connect(func() -> void: _animate(control, Vector2.ONE))
	control.resized.connect(func() -> void: control.pivot_offset = control.size / 2.0)


static func _animate(control: Control, target: Vector2) -> void:
	control.pivot_offset = control.size / 2.0
	var tween := control.create_tween()
	tween.tween_property(control, "scale", target, DURATION).set_trans(Tween.TRANS_BACK).set_ease(Tween.EASE_OUT)
