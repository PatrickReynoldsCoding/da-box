"use strict";

const DAYS = [
  ["mon", "Mon"], ["tue", "Tue"], ["wed", "Wed"], ["thu", "Thu"],
  ["fri", "Fri"], ["sat", "Sat"], ["sun", "Sun"],
];

const $ = (selector, root = document) => root.querySelector(selector);

class ApiError extends Error {
  constructor(status, detail) {
    super(typeof detail === "string" ? detail : JSON.stringify(detail));
    this.status = status;
    this.detail = detail;
  }
}

async function api(path, { method = "GET", body } = {}) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(`/api/admin${path}`, options);
  const text = await response.text();
  const data = text ? JSON.parse(text) : null;
  if (!response.ok) {
    if (response.status === 401 && path !== "/login") showView("login");
    throw new ApiError(response.status, data?.detail ?? response.statusText);
  }
  return data;
}

function showView(name) {
  for (const view of document.querySelectorAll(".view")) view.hidden = view.id !== `view-${name}`;
  $("#logout").hidden = name !== "main";
  if (name === "login") $("#login-pin").focus();
}

function showTab(name) {
  for (const button of document.querySelectorAll(".tabs button")) {
    button.classList.toggle("active", button.dataset.tab === name);
  }
  for (const tab of document.querySelectorAll(".tab")) tab.hidden = tab.id !== `tab-${name}`;
  const loaders = {
    home: loadHome, content: loadContent, settings: loadSettings, channels: loadChannels, guide: loadGuide, activity: loadActivity,
  };
  loaders[name]?.();
}

function setMessage(element, text, kind) {
  element.textContent = text;
  element.className = `message ${kind ?? ""}`;
}

function describeLoginError(error) {
  const reasons = {
    wrong_pin: () => `Wrong PIN. ${error.detail.attempts_before_lockout} tries left before a lockout.`,
    locked_out: () => `Too many wrong tries. Try again after ${new Date(error.detail.until).toLocaleTimeString()}.`,
    setup_required: () => "Finish the setup on the TV first.",
  };
  return reasons[error.detail?.reason]?.() ?? error.message;
}

async function start() {
  const session = await api("/session");
  if (session.setup_required) return showView("setup");
  if (!session.logged_in) return showView("login");
  showView("main");
  showTab("home");
}

// ---- Login ----

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = $("#login-message");
  try {
    await api("/login", { method: "POST", body: { pin: $("#login-pin").value } });
    $("#login-pin").value = "";
    setMessage(message, "");
    await start();
  } catch (error) {
    setMessage(message, describeLoginError(error), "error");
  }
});

$("#logout").addEventListener("click", async () => {
  await api("/logout", { method: "POST" });
  showView("login");
});

for (const button of document.querySelectorAll(".tabs button")) {
  button.addEventListener("click", () => showTab(button.dataset.tab));
}

// ---- Home ----

function renderParentMode(enabled) {
  $("#parent-mode").checked = enabled;
  $("#parent-mode-label").textContent = enabled ? "On" : "Off";
}

function renderToday(today) {
  if (today.unlimited) {
    $("#today-summary").textContent = "No limits right now (parent mode, or setup not done).";
    $("#today-games").textContent = "";
    $("#today-shutdown").textContent = "";
    return;
  }
  const left = Math.ceil((today.video_seconds_left ?? 0) / 60);
  $("#today-summary").textContent = `TV time used: ${today.used_minutes} of ${today.quota_minutes} min (${left} min left).${today.video_locked ? ` ${today.video_locked_reason}` : ""}`;
  $("#today-games").textContent = `Games: ${today.games_message}. Bedtime: ${today.bedtime ? today.bedtime.slice(11, 16) : "–"}.`;
  $("#today-shutdown").textContent = today.shutdown_at ? `The box turns off at ${today.shutdown_at.slice(11, 19)}. Extra time stops this.` : "";
}

for (const button of document.querySelectorAll("[data-extra-quota], [data-extra-games]")) {
  button.addEventListener("click", async () => {
    const body = { quota_minutes: Number(button.dataset.extraQuota ?? 0), game_minutes: Number(button.dataset.extraGames ?? 0) };
    renderToday(await api("/extra-time", { method: "POST", body }));
    setMessage($("#extra-message"), `Added: ${button.textContent.replace("+", "")} for today.`, "ok");
  });
}

async function loadHome() {
  const [status, sticks, today] = await Promise.all([api("/status"), api("/usb"), api("/today")]);
  renderToday(today);
  renderParentMode(status.parent_mode);
  $("#library-summary").textContent = `${status.film_count} films, ${status.album_count} albums. Time zone: ${status.timezone ?? "not set"}.`;
  const rows = sticks.map((stick) => {
    const row = document.createElement("li");
    row.textContent = `${stick.label} (${stick.path})`;
    return row;
  });
  if (rows.length === 0) {
    const none = document.createElement("li");
    none.className = "muted";
    none.textContent = "No USB stick in the box.";
    rows.push(none);
  }
  $("#usb-list").replaceChildren(...rows);
}

$("#parent-mode").addEventListener("change", async (event) => {
  const status = await api("/parent-mode", { method: "POST", body: { enabled: event.target.checked } });
  renderParentMode(status.parent_mode);
});

// ---- Content ----

const contentById = new Map();

function itemRow(item, subtitle, artClass, kind) {
  contentById.set(item.id, { ...item, kind });
  const row = document.createElement("li");
  row.addEventListener("click", () => openItem(item.id));
  const art = item.art_url ? document.createElement("img") : document.createElement("div");
  if (item.art_url) {
    art.src = item.art_url;
    art.alt = "";
    art.loading = "lazy";
  } else {
    art.className = "no-art";
  }
  if (artClass) art.classList.add(artClass);

  const info = document.createElement("div");
  info.className = "info";
  const title = document.createElement("div");
  title.textContent = item.title;
  if (item.source === "usb") {
    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = "USB";
    title.append(badge);
  }
  const sub = document.createElement("div");
  sub.className = "sub";
  sub.textContent = subtitle;
  info.append(title, sub);

  const toggle = document.createElement("label");
  toggle.className = "switch";
  toggle.addEventListener("click", (event) => event.stopPropagation());
  toggle.innerHTML = '<input type="checkbox"><span class="slider"></span><span></span>';
  const checkbox = $("input", toggle);
  const label = $("span:last-child", toggle);
  const render = () => { label.textContent = checkbox.checked ? "Visible" : "Hidden"; };
  checkbox.checked = !item.hidden;
  render();
  checkbox.addEventListener("change", async () => {
    await api(`/content/${item.id}/hidden`, { method: "POST", body: { hidden: !checkbox.checked } });
    render();
  });

  row.append(art, info, toggle);
  return row;
}

function renderContent(content) {
  const filmList = $("#film-list");
  contentById.clear();
  filmList.replaceChildren(...content.films.map((film) => itemRow(film, film.year ?? "", null, "film")));
  filmList.classList.toggle("empty", content.films.length === 0);

  const albumList = $("#album-list");
  albumList.replaceChildren(
    ...content.albums.map((album) => itemRow(album, `${album.artist} · ${album.track_count} tracks`, "album-art", "album")),
  );
  albumList.classList.toggle("empty", content.albums.length === 0);
}

async function loadContent() {
  const [content, games] = await Promise.all([api("/content"), api("/games")]);
  renderContent(content);
  const gameList = $("#game-list");
  gameList.replaceChildren(...games.map((game) => itemRow(game, game.system_name, "album-art", "game")));
  gameList.classList.toggle("empty", games.length === 0);
}

$("#rescan").addEventListener("click", async () => {
  renderContent(await api("/rescan", { method: "POST" }));
});

// ---- Upload ----

function uploadWithProgress(form, path) {
  const progress = $("progress", form);
  const message = $(".message", form);
  const button = $("button[type=submit]", form);

  const request = new XMLHttpRequest();
  request.open("POST", `/api/admin${path}`);
  request.upload.addEventListener("progress", (event) => {
    if (event.lengthComputable) progress.value = Math.round((event.loaded / event.total) * 100);
  });
  request.addEventListener("loadend", () => {
    progress.hidden = true;
    button.disabled = false;
    if (request.status === 200) {
      const result = JSON.parse(request.responseText);
      setMessage(message, `Saved: ${result.saved.join(", ")}`, "ok");
      form.reset();
    } else {
      let detail = request.statusText || "Upload failed";
      try { detail = JSON.parse(request.responseText).detail; } catch { /* keep statusText */ }
      setMessage(message, typeof detail === "string" ? detail : JSON.stringify(detail), "error");
    }
  });

  progress.value = 0;
  progress.hidden = false;
  button.disabled = true;
  setMessage(message, "Uploading…");
  request.send(new FormData(form));
}

$("#film-upload").addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.target;
  if (!form.year.value) form.year.disabled = true;
  uploadWithProgress(form, "/upload/film");
  form.year.disabled = false;
});

$("#music-upload").addEventListener("submit", (event) => {
  event.preventDefault();
  uploadWithProgress(event.target, "/upload/music");
});

// ---- Settings ----

const toInputTime = (value) => (value ? value.slice(0, 5) : "");

function renderDayRows(limits) {
  const rows = DAYS.map(([key, label]) => {
    const gameWindow = limits.game_windows[key];
    const row = document.createElement("tr");
    row.dataset.day = key;
    row.innerHTML = `
      <td>${label}</td>
      <td><input type="checkbox" class="games-on"></td>
      <td><input type="time" class="from"></td>
      <td><input type="time" class="to"></td>
      <td><input type="time" class="bedtime" required></td>`;
    const gamesOn = $(".games-on", row);
    const from = $(".from", row);
    const to = $(".to", row);
    gamesOn.checked = gameWindow !== null;
    from.value = toInputTime(gameWindow?.start);
    to.value = toInputTime(gameWindow?.end);
    $(".bedtime", row).value = toInputTime(limits.bedtimes[key]);
    const sync = () => { from.disabled = to.disabled = !gamesOn.checked; from.required = to.required = gamesOn.checked; };
    gamesOn.addEventListener("change", sync);
    sync();
    return row;
  });
  $("#day-rows").replaceChildren(...rows);
}

async function loadSettings() {
  loadAccounts();
  loadAppearance();
  loadUpdateStatus();
  const limits = await api("/settings");
  const form = $("#settings-form");
  form.daily_quota_minutes.value = limits.daily_quota_minutes;
  form.overrun_minutes.value = limits.overrun_minutes;
  for (const name of ["shared_quota", "bedtime_overrun", "usb_playback", "usb_games"]) form[name].checked = limits[name];
  renderDayRows(limits);
}

function readSettingsForm(form) {
  const gameWindows = {};
  const bedtimes = {};
  for (const row of document.querySelectorAll("#day-rows tr")) {
    const day = row.dataset.day;
    gameWindows[day] = $(".games-on", row).checked ? { start: $(".from", row).value, end: $(".to", row).value } : null;
    bedtimes[day] = $(".bedtime", row).value;
  }
  return {
    daily_quota_minutes: Number(form.daily_quota_minutes.value),
    shared_quota: form.shared_quota.checked,
    overrun_minutes: Number(form.overrun_minutes.value),
    game_windows: gameWindows,
    bedtimes,
    bedtime_overrun: form.bedtime_overrun.checked,
    usb_playback: form.usb_playback.checked,
    usb_games: form.usb_games.checked,
  };
}

function describeValidationError(error) {
  if (Array.isArray(error.detail)) return error.detail.map((problem) => problem.msg).join(". ");
  return error.message;
}

$("#settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = $(".message", event.target);
  try {
    await api("/settings", { method: "PUT", body: readSettingsForm(event.target) });
    setMessage(message, "Saved.", "ok");
  } catch (error) {
    setMessage(message, describeValidationError(error), "error");
  }
});

$("#pin-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  const message = $(".message", form);
  try {
    await api("/pin", { method: "POST", body: { current_pin: form.current_pin.value, new_pin: form.new_pin.value } });
    setMessage(message, "PIN changed.", "ok");
    form.reset();
  } catch (error) {
    setMessage(message, describeValidationError(error), "error");
  }
});

// ---- Item details (metadata, art, copy to box) ----

const STATUS_TEXT = {
  matched: "Details and art were found online.",
  not_found: "Nothing was found online. Search below, or edit the details.",
  no_account: "Waiting for a TMDB API key (Settings).",
  failed: "The last online search failed. Try again below.",
  manual: "Details set by hand.",
};

let openItemId = null;

function itemMessage(text, kind) {
  setMessage($("#item-message"), text, kind);
}

function renderItem(item) {
  document.body.classList.toggle("is-film", item.kind === "film");
  document.body.classList.toggle("is-album", item.kind === "album");
  document.body.classList.toggle("is-game", item.kind === "game");
  const art = $("#item-art");
  art.src = item.art_url ? `${item.art_url}?v=${Date.now()}` : "";
  art.style.visibility = item.art_url ? "visible" : "hidden";
  $("#item-title").textContent = item.title;
  $("#item-sub").textContent = item.kind === "film" ? (item.year ?? "") : `${item.artist}${item.year ? ` · ${item.year}` : ""}`;
  $("#item-status").textContent = STATUS_TEXT[item.metadata_status] ?? "Using the files' own details.";

  const edit = $("#item-edit");
  edit.title.value = item.title;
  edit.year.value = item.year ?? "";
  edit.plot.value = item.plot ?? "";

  const search = $("#item-search");
  search.title.value = item.title;
  search.year.value = item.year ?? "";
  search.artist.value = item.artist ?? "";
  $("#candidates").replaceChildren();
  $("#art-options").replaceChildren();

  $("#copy-section").hidden = item.source !== "usb";
  $("#item-stick").textContent = item.stick_label ?? "";
}

async function refreshOpenItem() {
  const content = await api("/content");
  renderContent(content);
  const item = contentById.get(openItemId);
  if (item) renderItem(item);
  return item;
}

function openItem(itemId) {
  openItemId = itemId;
  renderItem(contentById.get(itemId));
  itemMessage("");
  $("#item-dialog").showModal();
}

$("#item-edit").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  try {
    await api(`/content/${openItemId}/metadata`, {
      method: "PUT",
      body: { title: form.title.value, year: form.year.value ? Number(form.year.value) : null, plot: form.plot.value },
    });
    await refreshOpenItem();
    itemMessage("Saved.", "ok");
  } catch (error) {
    itemMessage(describeValidationError(error), "error");
  }
});

$("#item-reset").addEventListener("click", async () => {
  await api(`/content/${openItemId}/metadata`, { method: "DELETE" });
  itemMessage("Reset. The box looks for details again in a few seconds.", "ok");
  setTimeout(refreshOpenItem, 4000);
  await refreshOpenItem();
});

function candidateRow(candidate) {
  const row = document.createElement("li");
  const image = document.createElement("img");
  image.alt = "";
  // Not every match has a cover. Show an empty box instead of a broken image.
  image.addEventListener("error", () => image.removeAttribute("src"));
  if (candidate.preview_url) image.src = candidate.preview_url;
  const info = document.createElement("div");
  const title = document.createElement("div");
  title.textContent = `${candidate.title}${candidate.year ? ` (${candidate.year})` : ""}`;
  const sub = document.createElement("div");
  sub.className = "sub";
  sub.textContent = [candidate.artist, candidate.description].filter(Boolean).join(" · ").slice(0, 160);
  info.append(title, sub);
  row.append(image, info);
  row.addEventListener("click", async () => {
    itemMessage("Saving…");
    try {
      await api(`/content/${openItemId}/metadata/apply`, { method: "POST", body: candidate });
      await refreshOpenItem();
      itemMessage("Match saved.", "ok");
    } catch (error) {
      itemMessage(describeValidationError(error), "error");
    }
  });
  return row;
}

$("#item-search").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  itemMessage("Searching…");
  try {
    const candidates = await api(`/content/${openItemId}/metadata/search`, {
      method: "POST",
      body: { title: form.title.value, year: form.year.value ? Number(form.year.value) : null, artist: form.artist.value },
    });
    $("#candidates").replaceChildren(...candidates.map(candidateRow));
    itemMessage(candidates.length ? "Pick the right one:" : "Nothing found. Try other words.");
  } catch (error) {
    itemMessage(describeValidationError(error), "error");
  }
});

$("#art-options-button").addEventListener("click", async () => {
  const options = await api(`/content/${openItemId}/metadata/art-options`);
  if (options.length === 0) {
    itemMessage("No other art. Find a match first, or upload an image.");
    return;
  }
  $("#art-options").replaceChildren(...options.map((option) => {
    const image = document.createElement("img");
    image.src = option.preview_url;
    image.alt = "";
    image.loading = "lazy";
    image.addEventListener("click", async () => {
      await api(`/content/${openItemId}/metadata/art`, { method: "POST", body: { url: option.full_url } });
      await refreshOpenItem();
      itemMessage("Art saved.", "ok");
    });
    return image;
  }));
});

$("#art-upload").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const body = new FormData();
  body.append("image", file);
  const response = await fetch(`/api/admin/content/${openItemId}/metadata/art-upload`, { method: "POST", body });
  event.target.value = "";
  if (response.ok) {
    await refreshOpenItem();
    itemMessage("Art saved.", "ok");
  } else {
    itemMessage((await response.json()).detail ?? "Upload failed", "error");
  }
});

$("#copy-to-box").addEventListener("click", async () => {
  itemMessage("Copying… this can take a few minutes for a film.");
  $("#copy-to-box").disabled = true;
  try {
    const content = await api(`/content/${openItemId}/copy-to-box`, { method: "POST" });
    renderContent(content);
    itemMessage("Copied to the box.", "ok");
    $("#copy-section").hidden = true;
  } catch (error) {
    itemMessage(describeValidationError(error), "error");
  } finally {
    $("#copy-to-box").disabled = false;
  }
});

// ---- Channels ----

const POOL_KINDS = { video: ["film", "show"], music: ["album"] };
const KIND_LABELS = { film: "Film", show: "Show", album: "Album" };
let poolItems = [];
let editingChannel = null;

async function loadChannels() {
  const channels = await api("/channels");
  const rows = channels.map((channel) => {
    const row = document.createElement("li");
    const info = document.createElement("div");
    info.className = "info";
    const title = document.createElement("div");
    title.textContent = `${channel.number}. ${channel.name}`;
    const sub = document.createElement("div");
    sub.className = "sub";
    const openDays = Object.values(channel.hours).filter(Boolean).length;
    sub.textContent = `${channel.kind === "music" ? "Music" : "Video"} · ${channel.order === "shuffle" ? "shuffle" : "in order"} · ${channel.pool.length} in pool · open ${openDays} days`;
    info.append(title, sub);
    row.append(info);
    row.addEventListener("click", () => openChannel(channel));
    return row;
  });
  $("#channel-list").replaceChildren(...rows);
  $("#channel-list").classList.toggle("empty", rows.length === 0);
}

function renderPool(kind, selected) {
  const allowed = POOL_KINDS[kind];
  const rows = poolItems.filter((item) => allowed.includes(item.kind)).map((item) => {
    const row = document.createElement("li");
    const label = document.createElement("label");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.value = `${item.kind}:${item.id}`;
    box.checked = selected.has(box.value);
    label.append(box, ` ${KIND_LABELS[item.kind]}: ${item.title}`);
    const detail = document.createElement("span");
    detail.className = "muted small";
    detail.textContent = item.detail ? ` (${item.detail})` : "";
    label.append(detail);
    row.append(label);
    return row;
  });
  $("#pool-list").replaceChildren(...rows);
}

function renderHours(hours) {
  const rows = DAYS.map(([key, label]) => {
    const openHours = hours[key];
    const row = document.createElement("tr");
    row.dataset.day = key;
    row.innerHTML = `<td>${label}</td><td><input type="checkbox" class="open"></td>
      <td><input type="time" class="from"></td><td><input type="time" class="to"></td>`;
    const open = $(".open", row);
    const from = $(".from", row);
    const to = $(".to", row);
    open.checked = Boolean(openHours);
    from.value = toInputTime(openHours?.start);
    to.value = toInputTime(openHours?.end);
    const sync = () => { from.disabled = to.disabled = !open.checked; from.required = to.required = open.checked; };
    open.addEventListener("change", sync);
    sync();
    return row;
  });
  $("#hours-rows").replaceChildren(...rows);
}

async function openChannel(channel) {
  editingChannel = channel;
  poolItems = await api("/pool");
  const form = $("#channel-form");
  form.reset();
  $("#channel-form-title").textContent = channel ? `Edit ${channel.name}` : "New channel";
  form.name.value = channel?.name ?? "";
  form.kind.value = channel?.kind ?? "video";
  form.order.value = channel?.order ?? "in_order";
  const selected = new Set((channel?.pool ?? []).map((entry) => `${entry.kind}:${entry.id}`));
  renderPool(form.kind.value, selected);
  const emptyHours = Object.fromEntries(DAYS.map(([key]) => [key, null]));
  renderHours(channel?.hours ?? emptyHours);
  $("#delete-channel").hidden = !channel;
  setMessage($(".message", form), "");
  $("#channel-dialog").showModal();
}

$("#new-channel").addEventListener("click", () => openChannel(null));
$("#channel-form").kind.addEventListener("change", (event) => renderPool(event.target.value, new Set()));

$("#copy-monday-hours").addEventListener("click", () => {
  const rows = [...document.querySelectorAll("#hours-rows tr")];
  const monday = rows[0];
  for (const row of rows.slice(1)) {
    $(".open", row).checked = $(".open", monday).checked;
    $(".from", row).value = $(".from", monday).value;
    $(".to", row).value = $(".to", monday).value;
    $(".open", row).dispatchEvent(new Event("change"));
  }
});

$("#channel-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  const hours = {};
  for (const row of document.querySelectorAll("#hours-rows tr")) {
    hours[row.dataset.day] = $(".open", row).checked ? { start: $(".from", row).value, end: $(".to", row).value } : null;
  }
  const pool = [...document.querySelectorAll("#pool-list input:checked")].map((box) => {
    const [kind, id] = box.value.split(":");
    return { kind, id };
  });
  const body = { name: form.name.value, kind: form.kind.value, order: form.order.value, pool, hours };
  try {
    if (editingChannel) await api(`/channels/${editingChannel.id}`, { method: "PUT", body });
    else await api("/channels", { method: "POST", body });
    $("#channel-dialog").close();
    loadChannels();
  } catch (error) {
    setMessage($(".message", form), describeValidationError(error), "error");
  }
});

$("#delete-channel").addEventListener("click", async () => {
  if (!editingChannel || !confirm(`Delete the channel "${editingChannel.name}"?`)) return;
  await api(`/channels/${editingChannel.id}`, { method: "DELETE" });
  $("#channel-dialog").close();
  loadChannels();
});

// ---- Guide ----

// Pixels per minute: big enough that the shortest programme of the week can be read and
// clicked (music tracks and short episodes), but a long film does not fill many screens.
const SCALE_LIMITS = { smallest: 1.6, biggest: 12 };
const SHORTEST_BLOCK_PX = 24;
const ADD_STEP_MINUTES = 5;
const MINUTES_PER_DAY = 24 * 60;

let guideChannelId = null;
let guideDay = null;
let guideWeek = null;
let editingSlot = null;
let programmeChoices = [];

const timeOf = (iso) => iso.slice(11, 16);
const dayOf = (iso) => iso.slice(0, 10);
const minutesOf = (clock) => Number(clock.slice(0, 2)) * 60 + Number(clock.slice(3, 5));
const clockOf = (minutes) => `${String(Math.floor(minutes / 60)).padStart(2, "0")}:${String(minutes % 60).padStart(2, "0")}`;
// A slot that ends at midnight ends at minute 1440 of its own day.
const endMinutesOf = (slot) => (dayOf(slot.end) > dayOf(slot.start) ? MINUTES_PER_DAY : minutesOf(timeOf(slot.end)));

function addDays(day, count) {
  const moment = new Date(`${day}T00:00:00Z`);
  moment.setUTCDate(moment.getUTCDate() + count);
  return moment.toISOString().slice(0, 10);
}

function dayLabel(day, options) {
  return new Date(`${day}T00:00:00Z`).toLocaleDateString(undefined, { timeZone: "UTC", ...options });
}

function weekdayKey(day) {
  return DAYS[(new Date(`${day}T00:00:00Z`).getUTCDay() + 6) % 7][0];
}

/** The minutes after midnight that the table shows: the open hours and every slot, in whole hours. */
function guideRange(week) {
  let first = MINUTES_PER_DAY;
  let last = 0;
  for (const day of week.days) {
    const hours = week.channel.hours[weekdayKey(day)];
    if (hours) {
      first = Math.min(first, minutesOf(hours.start));
      last = Math.max(last, minutesOf(hours.end));
    }
  }
  for (const slot of week.slots) {
    first = Math.min(first, minutesOf(timeOf(slot.start)));
    last = Math.max(last, endMinutesOf(slot));
  }
  if (last <= first) return null;
  return { first: Math.floor(first / 60) * 60, last: Math.ceil(last / 60) * 60 };
}

function guideScale(slots) {
  let shortest = Infinity;
  for (const slot of slots) {
    if (slot.title) shortest = Math.min(shortest, endMinutesOf(slot) - minutesOf(timeOf(slot.start)));
  }
  const wanted = SHORTEST_BLOCK_PX / Math.max(shortest, 1);
  return Math.min(Math.max(wanted, SCALE_LIMITS.smallest), SCALE_LIMITS.biggest);
}

function guideBlock(slot, range, scale) {
  const block = document.createElement("button");
  block.type = "button";
  block.className = `guide-block${slot.title ? "" : " empty"}${slot.edited ? " edited" : ""}`;
  const start = minutesOf(timeOf(slot.start));
  block.style.top = `${(start - range.first) * scale}px`;
  block.style.height = `${(endMinutesOf(slot) - start) * scale}px`;
  const time = document.createElement("span");
  time.className = "time";
  time.textContent = `${timeOf(slot.start)} `;
  const title = document.createElement("span");
  title.className = "title";
  title.textContent = slot.title ?? "Empty";
  block.append(time, title);
  if (slot.edited) {
    const badge = document.createElement("span");
    badge.className = "badge edited";
    badge.textContent = "changed";
    block.append(badge);
  }
  if (slot.subtitle) {
    const sub = document.createElement("span");
    sub.className = "sub";
    sub.textContent = slot.subtitle;
    block.append(sub);
  }
  block.title = `${timeOf(slot.start)}–${timeOf(slot.end)} ${slot.title ?? "Empty"}${slot.subtitle ? ` · ${slot.subtitle}` : ""}`;
  block.addEventListener("click", (event) => {
    event.stopPropagation();
    openSlot(slot);
  });
  return block;
}

function guideDayHeader(day, week, shuffles) {
  const header = document.createElement("div");
  header.className = `guide-head${day === week.today ? " today" : ""}`;
  const name = document.createElement("div");
  name.textContent = dayLabel(day, { weekday: "short", day: "numeric", month: "short" });
  header.append(name);
  if (shuffles) {
    const shuffle = document.createElement("button");
    shuffle.className = "secondary";
    shuffle.textContent = "Shuffle day";
    shuffle.addEventListener("click", () => guideAction(() => api("/guide/shuffle", {
      method: "POST", body: { channel_id: week.channel.id, day, whole_week: false },
    })));
    header.append(shuffle);
  }
  return header;
}

function guideTimes(range, scale) {
  const times = document.createElement("div");
  times.className = "guide-times";
  times.style.height = `${(range.last - range.first) * scale}px`;
  for (let minutes = range.first; minutes < range.last; minutes += 60) {
    const label = document.createElement("span");
    label.style.top = `${(minutes - range.first) * scale}px`;
    label.textContent = clockOf(minutes);
    times.append(label);
  }
  return times;
}

function guideDayColumn(day, week, range, scale) {
  const column = document.createElement("div");
  column.className = "guide-day";
  column.style.height = `${(range.last - range.first) * scale}px`;
  const hours = week.channel.hours[weekdayKey(day)];
  if (hours) {
    const top = (minutesOf(hours.start) - range.first) * scale;
    const open = document.createElement("div");
    open.className = "guide-open";
    open.style.top = `${top}px`;
    open.style.height = `${(minutesOf(hours.end) - minutesOf(hours.start)) * scale}px`;
    // Keeps the hour lines of the open hours in line with those of the closed hours.
    open.style.backgroundPositionY = `${-top}px`;
    column.append(open);
  }
  for (const slot of week.slots) {
    if (dayOf(slot.start) === day) column.append(guideBlock(slot, range, scale));
  }
  column.addEventListener("click", (event) => {
    const offset = event.clientY - column.getBoundingClientRect().top;
    const minutes = range.first + Math.floor(offset / scale / ADD_STEP_MINUTES) * ADD_STEP_MINUTES;
    openSlot({ id: null, start: `${day}T${clockOf(minutes)}:00`, end: null, title: null, edited: false });
  });
  return column;
}

function renderGuideWeek(week) {
  const range = guideRange(week);
  if (!range) {
    const closed = document.createElement("p");
    closed.className = "muted";
    closed.textContent = "This channel is closed all week. Set its hours in the Channels tab.";
    $("#guide-week").replaceChildren(closed);
    return;
  }
  const scale = guideScale(week.slots);
  const shuffles = week.channel.order === "shuffle";
  const table = document.createElement("div");
  table.className = "guide-table";
  table.style.setProperty("--hour", `${60 * scale}px`);
  const corner = document.createElement("div");
  corner.className = "guide-corner";
  table.append(corner);
  for (const day of week.days) table.append(guideDayHeader(day, week, shuffles));
  table.append(guideTimes(range, scale));
  for (const day of week.days) table.append(guideDayColumn(day, week, range, scale));
  $("#guide-week").replaceChildren(table);
}

async function loadGuide() {
  const channels = await api("/channels");
  const hasChannels = channels.length > 0;
  $("#guide-no-channels").hidden = hasChannels;
  $("#guide-controls").hidden = !hasChannels;
  $("#guide-week-action").hidden = !hasChannels;
  if (!hasChannels) return;
  if (!channels.some((channel) => channel.id === guideChannelId)) guideChannelId = channels[0].id;
  $("#guide-channel").replaceChildren(...channels.map((channel) => new Option(`${channel.number}. ${channel.name}`, channel.id)));
  $("#guide-channel").value = guideChannelId;
  await loadGuideWeek();
}

async function loadGuideWeek() {
  const params = new URLSearchParams({ channel_id: guideChannelId });
  if (guideDay) params.set("day", guideDay);
  guideWeek = await api(`/guide/week?${params}`);
  guideDay = guideWeek.week_start;
  const shuffles = guideWeek.channel.order === "shuffle";
  const dateOptions = { day: "numeric", month: "short" };
  $("#guide-week-action").textContent = shuffles ? "Shuffle week" : "Fill again";
  $("#guide-week-label").textContent = `${dayLabel(guideWeek.days[0], dateOptions)} – ${dayLabel(guideWeek.days[6], dateOptions)}`;
  $("#guide-help").textContent = shuffles
    ? "Click a programme to change or empty it. Click an empty place to add a programme there. Shuffle gives a new random order. Programmes you changed or emptied stay."
    : "Click a programme to change or empty it. Click an empty place to add a programme there. \"Fill again\" fills the week again in order, for example after new files. Programmes you changed or emptied stay.";
  renderGuideWeek(guideWeek);
}

async function guideAction(action) {
  setMessage($("#guide-message"), "");
  try {
    await action();
    await loadGuideWeek();
  } catch (error) {
    setMessage($("#guide-message"), describeValidationError(error), "error");
  }
}

$("#guide-channel").addEventListener("change", () => {
  guideChannelId = $("#guide-channel").value;
  loadGuideWeek();
});
$("#guide-previous").addEventListener("click", () => {
  guideDay = addDays(guideDay, -7);
  loadGuideWeek();
});
$("#guide-next").addEventListener("click", () => {
  guideDay = addDays(guideDay, 7);
  loadGuideWeek();
});
$("#guide-this-week").addEventListener("click", () => {
  guideDay = null;
  loadGuideWeek();
});
$("#guide-week-action").addEventListener("click", () => guideAction(() => (
  guideWeek.channel.order === "shuffle"
    ? api("/guide/shuffle", { method: "POST", body: { channel_id: guideWeek.channel.id, day: guideWeek.week_start, whole_week: true } })
    : api(`/guide/generate?day=${guideWeek.week_start}`, { method: "POST" })
)));

function renderProgrammeChoices() {
  const filter = $("#programme-filter").value.toLowerCase();
  const rows = programmeChoices
    .filter((choice) => `${choice.title} ${choice.subtitle ?? ""}`.toLowerCase().includes(filter))
    .slice(0, 100)
    .map((choice) => {
      const row = document.createElement("li");
      const info = document.createElement("div");
      const title = document.createElement("div");
      title.textContent = choice.title;
      const sub = document.createElement("div");
      sub.className = "sub";
      sub.textContent = `${choice.subtitle ?? ""}${choice.subtitle ? " · " : ""}${choice.minutes} min`;
      info.append(title, sub);
      row.append(info);
      row.addEventListener("click", async () => {
        try {
          await api("/guide/slots", {
            method: "POST",
            body: { channel_id: editingSlot.channel.id, start: editingSlot.slot.start, ref: choice.ref, replace_slot_id: editingSlot.slot.id },
          });
          $("#slot-dialog").close();
          loadGuideWeek();
        } catch (error) {
          setMessage($("#slot-message"), describeValidationError(error), "error");
        }
      });
      return row;
    });
  $("#programme-list").replaceChildren(...rows);
}

async function openSlot(slot) {
  const { channel } = guideWeek;
  editingSlot = { slot, channel };
  const when = `${channel.name}, ${dayLabel(dayOf(slot.start), { weekday: "long", day: "numeric", month: "short" })} at ${timeOf(slot.start)}`;
  $("#slot-heading").textContent = slot.id ? "Change this programme" : "Add a programme";
  $("#slot-when").textContent = slot.id
    ? `${when}. Pick a new programme: it starts at this time.`
    : `${when}. Programmes the box filled in make way. Programmes you changed or emptied do not move.`;
  $("#slot-empty").hidden = !slot.title;
  $("#slot-undo").hidden = !slot.edited;
  $("#programme-filter").value = "";
  setMessage($("#slot-message"), "");
  programmeChoices = await api(`/programmes?kind=${channel.kind}`);
  renderProgrammeChoices();
  $("#slot-dialog").showModal();
}

async function changeEditingSlot(action) {
  const { slot } = editingSlot;
  try {
    await api(`/guide/slots/${slot.id}/${action}`, { method: "POST", body: { start: slot.start } });
    $("#slot-dialog").close();
    loadGuideWeek();
  } catch (error) {
    setMessage($("#slot-message"), describeValidationError(error), "error");
  }
}

$("#slot-empty").addEventListener("click", () => changeEditingSlot("clear"));
$("#slot-undo").addEventListener("click", () => changeEditingSlot("restore"));
$("#programme-filter").addEventListener("input", renderProgrammeChoices);

// ---- Activity ----

const KIND_NAMES = { video: "TV / film", game: "Game", audio: "Music" };

async function loadActivity() {
  const activity = await api("/activity");
  $("#activity-totals").replaceChildren(...activity.totals.map((day) => {
    const row = document.createElement("tr");
    for (const text of [day.day, `${day.video_minutes} min`, `${day.game_minutes} min`, `${day.music_minutes} min`]) {
      const cell = document.createElement("td");
      cell.textContent = text;
      row.append(cell);
    }
    return row;
  }));
  const rows = activity.entries.map((entry) => {
    const row = document.createElement("li");
    const when = document.createElement("span");
    when.className = "when";
    when.textContent = `${entry.started.slice(5, 10)} ${entry.started.slice(11, 16)}`;
    const what = document.createElement("span");
    what.textContent = `${KIND_NAMES[entry.kind] ?? entry.kind}: ${entry.title}`;
    const length = document.createElement("span");
    length.className = "length";
    length.textContent = `${Math.max(1, Math.round(entry.seconds / 60))} min`;
    row.append(when, what, length);
    return row;
  });
  $("#activity-list").replaceChildren(...rows);
  $("#activity-list").classList.toggle("empty", rows.length === 0);
  $("#activity-list").classList.toggle("items", rows.length === 0);
}

// ---- Appearance, backup, update ----

async function loadAppearance() {
  const appearance = await api("/appearance");
  const form = $("#appearance-form");
  form.theme.value = appearance.theme;
  form.sounds.checked = appearance.sounds;
}

$("#appearance-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  await api("/appearance", { method: "PUT", body: { theme: form.theme.value, sounds: form.sounds.checked } });
  setMessage($(".message", form), "Saved. The TV changes in a few seconds.", "ok");
});

$("#restore-file").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  event.target.value = "";
  if (!file || !confirm("Restore this backup? It replaces all settings, channels and the guide.")) return;
  const body = new FormData();
  body.append("backup_file", file);
  const response = await fetch("/api/admin/restore", { method: "POST", body });
  const result = await response.json();
  setMessage($("#backup-message"), response.ok ? "Restored." : result.detail, response.ok ? "ok" : "error");
});

let updatePoll = null;

function renderUpdate(status) {
  $("#update-status").textContent = status.running ? "Updating… this can take some minutes." : (status.last_result ? `Last update: ${status.last_result}. The log below shows when.` : "No update yet.");
  $("#start-update").disabled = status.running;
  $("#update-log").hidden = status.log.length === 0;
  $("#update-log").textContent = status.log.join("\n");
  clearTimeout(updatePoll);
  if (status.running) updatePoll = setTimeout(loadUpdateStatus, 3000);
}

async function loadUpdateStatus() {
  renderUpdate(await api("/system-update"));
}

$("#start-update").addEventListener("click", async () => {
  if (!confirm("Update the box now? Videos and games keep working, but it can take some minutes.")) return;
  try {
    renderUpdate(await api("/system-update", { method: "POST" }));
  } catch (error) {
    $("#update-status").textContent = error.message;
  }
});

// ---- Accounts ----

async function loadAccounts() {
  const accounts = await api("/accounts");
  $("#tmdb-status").textContent = accounts.tmdb_api_key_set ? "A TMDB key is saved." : "No TMDB key yet.";
}

$("#accounts-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  const message = $(".message", form);
  if (!form.tmdb_api_key.value.trim()) return setMessage(message, "Paste a key first.", "error");
  await api("/accounts", { method: "PUT", body: { tmdb_api_key: form.tmdb_api_key.value } });
  form.reset();
  setMessage(message, "Saved. The box now fetches film art.", "ok");
  loadAccounts();
});

$("#remove-tmdb").addEventListener("click", async () => {
  await api("/accounts", { method: "PUT", body: { tmdb_api_key: "" } });
  loadAccounts();
});

$("#rerun-setup").addEventListener("click", async () => {
  if (!confirm("Run the setup on the TV again? The box shows the setup screens until it is complete.")) return;
  await api("/setup/rerun", { method: "POST" });
  showView("setup");
});

start().catch((error) => {
  $("#view-loading").innerHTML = `<p class="message error">Cannot reach the box: ${error.message}</p>`;
});
