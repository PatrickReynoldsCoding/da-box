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
  const [status, sticks] = await Promise.all([api("/status"), api("/usb")]);
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
  loadAccounts();
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
