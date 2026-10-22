extends Node
## Talks to the box service (data, setup) and the player agent (mpv) over HTTP on localhost.

## Emitted when the box state (setup needed, parent mode) changes.
signal state_changed(state: Dictionary)

var service_url := "http://127.0.0.1:80"
var agent_url := "http://127.0.0.1:8091"

var state: Dictionary = {}
var _texture_cache: Dictionary = {}


class Reply:
	var ok: bool
	var status: int
	var data: Variant

	func _init(reply_ok: bool, reply_status: int, reply_data: Variant) -> void:
		ok = reply_ok
		status = reply_status
		data = reply_data


func _ready() -> void:
	for argument in OS.get_cmdline_user_args():
		if argument.begins_with("--service="):
			service_url = argument.trim_prefix("--service=")
		elif argument.begins_with("--agent="):
			agent_url = argument.trim_prefix("--agent=")
		elif argument.begins_with("--smoke-test="):
			var driver: Node = load("res://tests/smoke_driver.gd").new(argument.trim_prefix("--smoke-test="))
			add_child(driver)


func service_get(path: String) -> Reply:
	return await _request(service_url + path, HTTPClient.METHOD_GET, null)


func service_post(path: String, body: Variant = {}) -> Reply:
	return await _request(service_url + path, HTTPClient.METHOD_POST, body)


func agent_get(path: String) -> Reply:
	return await _request(agent_url + path, HTTPClient.METHOD_GET, null)


func agent_post(path: String, body: Variant = {}) -> Reply:
	return await _request(agent_url + path, HTTPClient.METHOD_POST, body)


## Loads a JPEG or PNG from the service. Returns null if there is none.
func texture(path: String) -> Texture2D:
	if path.is_empty():
		return null
	if _texture_cache.has(path):
		return _texture_cache[path]
	var bytes := await _request_bytes(service_url + path)
	var image := _image_from_bytes(bytes)
	var loaded: Texture2D = ImageTexture.create_from_image(image) if image != null else null
	_texture_cache[path] = loaded
	return loaded


func clear_texture_cache() -> void:
	_texture_cache.clear()


## Reloads /box/state. Returns false if the service cannot be reached.
func refresh_state() -> bool:
	var reply := await service_get("/box/state")
	if not reply.ok:
		return false
	var new_state: Dictionary = reply.data
	if new_state != state:
		state = new_state
		state_changed.emit(state)
	return true


func parent_mode() -> bool:
	return state.get("parent_mode", false)


func _request(url: String, method: HTTPClient.Method, body: Variant) -> Reply:
	var http := HTTPRequest.new()
	add_child(http)
	var headers := PackedStringArray()
	var payload := ""
	if body != null:
		headers.append("Content-Type: application/json")
		payload = JSON.stringify(body)
	if http.request(url, headers, method, payload) != OK:
		http.queue_free()
		return Reply.new(false, 0, null)
	var result: Array = await http.request_completed
	http.queue_free()
	var status: int = result[1]
	var bytes: PackedByteArray = result[3]
	var parsed: Variant = JSON.parse_string(bytes.get_string_from_utf8()) if bytes.size() > 0 else null
	var ok: bool = result[0] == HTTPRequest.RESULT_SUCCESS and status >= 200 and status < 300
	return Reply.new(ok, status, parsed)


func _request_bytes(url: String) -> PackedByteArray:
	var http := HTTPRequest.new()
	add_child(http)
	if http.request(url) != OK:
		http.queue_free()
		return PackedByteArray()
	var result: Array = await http.request_completed
	http.queue_free()
	if result[0] != HTTPRequest.RESULT_SUCCESS or result[1] != 200:
		return PackedByteArray()
	return result[3]


func _image_from_bytes(bytes: PackedByteArray) -> Image:
	if bytes.size() < 4:
		return null
	var image := Image.new()
	var is_png := bytes[0] == 0x89 and bytes[1] == 0x50
	var error := image.load_png_from_buffer(bytes) if is_png else image.load_jpg_from_buffer(bytes)
	return image if error == OK else null
