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
  const loaders = { home: loadHome, content: loadContent, settings: loadSettings };
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

async function loadHome() {
  const status = await api("/status");
  renderParentMode(status.parent_mode);
  $("#library-summary").textContent = `${status.film_count} films, ${status.album_count} albums. Time zone: ${status.timezone ?? "not set"}.`;
}

$("#parent-mode").addEventListener("change", async (event) => {
  const status = await api("/parent-mode", { method: "POST", body: { enabled: event.target.checked } });
  renderParentMode(status.parent_mode);
});

// ---- Content ----

function itemRow(item, subtitle, artClass) {
  const row = document.createElement("li");
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
  const sub = document.createElement("div");
  sub.className = "sub";
  sub.textContent = subtitle;
  info.append(title, sub);

  const toggle = document.createElement("label");
  toggle.className = "switch";
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
  filmList.replaceChildren(...content.films.map((film) => itemRow(film, film.year ?? "")));
  filmList.classList.toggle("empty", content.films.length === 0);

  const albumList = $("#album-list");
  albumList.replaceChildren(
    ...content.albums.map((album) => itemRow(album, `${album.artist} · ${album.track_count} tracks`, "album-art")),
  );
  albumList.classList.toggle("empty", content.albums.length === 0);
}

async function loadContent() {
  renderContent(await api("/content"));
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

$("#rerun-setup").addEventListener("click", async () => {
  if (!confirm("Run the setup on the TV again? The box shows the setup screens until it is complete.")) return;
  await api("/setup/rerun", { method: "POST" });
  showView("setup");
});

start().catch((error) => {
  $("#view-loading").innerHTML = `<p class="message error">Cannot reach the box: ${error.message}</p>`;
});
