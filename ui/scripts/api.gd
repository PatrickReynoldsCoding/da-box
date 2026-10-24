extends Node
## Talks to the box service (data, setup) and the player agent (mpv) over HTTP on localhost.

## Emitted when the box state (setup needed, parent mode) changes.
signal state_changed(state: Dictionary)
## Emitted after each limits refresh (time left, games open, warnings, shut-down).
signal limits_changed(limits: Dictionary)
## Emitted after each refresh of the Copy from USB job.
signal copy_changed(progress: Dictionary)

var service_url := "http://127.0.0.1:80"
var agent_url := "http://127.0.0.1:8091"
## Key tests set this: every request fails at once, without the network.
var offline := false

var state: Dictionary = {}
var limits: Dictionary = {}
var copy_progress: Dictionary = {}
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


func service_put(path: String, body: Variant = {}) -> Reply:
	return await _request(service_url + path, HTTPClient.METHOD_PUT, body)


func service_delete(path: String) -> Reply:
	return await _request(service_url + path, HTTPClient.METHOD_DELETE, null)


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


func refresh_limits() -> void:
	var reply := await service_get("/box/limits")
	if reply.ok:
		limits = reply.data
		limits_changed.emit(limits)


func refresh_copy() -> void:
	var reply := await service_get("/box/usb/copy")
	if reply.ok:
		copy_progress = reply.data
		copy_changed.emit(copy_progress)


## The service's error text ("detail"), or the fallback.
static func error_text(reply: Reply, fallback: String) -> String:
	if reply.data is Dictionary and reply.data.get("detail") is String:
		return reply.data["detail"]
	return fallback


func copy_running() -> bool:
	return copy_progress.get("state") == "copying"


## Plays songs from the music API in this order. Box songs carry their id, so
## Now playing can add them to a playlist (USB songs cannot go on one).
func play_songs(songs: Array, start_index: int = 0) -> bool:
	var items := []
	for song in songs:
		items.append({
			"path": song["path"], "title": song["title"], "artist": song["artist"],
			"song_id": song["id"] if song.get("source") == "box" else null,
		})
	var reply := await agent_post("/play", {"kind": "audio", "items": items, "start_index": start_index})
	return reply.ok


## "1.4 GB", "350 MB".
static func size_text(bytes: float) -> String:
	var units := ["bytes", "KB", "MB", "GB", "TB"]
	var unit := 0
	while bytes >= 1000.0 and unit < units.size() - 1:
		bytes /= 1000.0
		unit += 1
	if unit == 0:
		return "%d bytes" % int(bytes)
	return ("%.1f %s" if bytes < 10.0 else "%d %s") % [bytes, units[unit]]


## Seconds of box-local wall-clock time, for comparing times from the service.
static func wall_seconds(iso_time: Variant) -> float:
	return Time.get_unix_time_from_datetime_string(iso_time) if iso_time is String else 0.0


## True if a video of this length can still start now (rule c).
func video_fits(seconds: float) -> bool:
	if limits.get("unlimited", true):
		return true
	if limits.get("video_locked", false) or limits.get("video_deadline") == null:
		return false
	return wall_seconds(limits["now"]) + seconds <= wall_seconds(limits["video_deadline"])


## Asks the service before a video starts. Returns "" if allowed, else the reason.
func approve_video(seconds: float) -> String:
	var reply := await service_post("/box/limits/video", {"seconds": maxf(seconds, 1.0)})
	if not reply.ok:
		return "The box could not check the time left."
	return "" if reply.data["allowed"] else String(reply.data["reason"])


static func minutes_text(seconds: float) -> String:
	var minutes := int(ceil(seconds / 60.0))
	if minutes >= 60:
		return "%d h %d min" % [minutes / 60, minutes % 60] if minutes % 60 else "%d h" % (minutes / 60)
	return "%d min" % minutes


func _request(url: String, method: HTTPClient.Method, body: Variant) -> Reply:
	if offline:
		return Reply.new(false, 0, null)
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
	if offline:
		return PackedByteArray()
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
