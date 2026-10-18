// Shared state for both views: config, the character list, which one is
// selected, and which view is showing.
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[ch]));

const App = {
  config: {},
  characters: [],
  selected: null,
  listeners: { config: [], select: [], list: [] },
  // Set by a view to stop the selection changing (live session, unsaved edits).
  guards: [],

  async api(method, url, body) {
    const r = await fetch(url, {
      method,
      headers: body !== undefined ? { "Content-Type": "application/json" } : {},
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    const ct = r.headers.get("content-type") || "";
    const data = ct.includes("json") ? await r.json() : await r.blob();
    if (!r.ok) {
      const err = new Error((data && data.error) || `HTTP ${r.status}`);
      err.errors = (data && data.errors) || [];
      throw err;
    }
    return data;
  },

  async loadCharacters(selectId) {
    this.characters = await this.api("GET", "/api/characters");
    const ids = this.characters.map((c) => c.id);
    let want = selectId || this.selected || remembered() || this.config.default_character;
    if (!ids.includes(want)) want = ids.includes(this.config.default_character) ? this.config.default_character : ids[0];
    const sel = $("character");
    sel.innerHTML = this.characters
      .map((c) => `<option value="${esc(c.id)}">${esc(c.name)}${c.errors.length ? " (has errors)" : ""}</option>`)
      .join("");
    if (want === this.selected) {
      // Same character (after a save): refresh the list, keep the editor as is.
      sel.value = want;
      this.listeners.list.forEach((fn) => fn(this.characters));
    } else {
      this.selected = null;
      this.select(want, true);
      this.listeners.list.forEach((fn) => fn(this.characters));
    }
  },

  current() {
    return this.characters.find((c) => c.id === this.selected);
  },

  select(id, force) {
    if (!force && id === this.selected) return true;
    if (!force && this.guards.some((g) => !g(id))) {
      $("character").value = this.selected;
      return false;
    }
    this.selected = id;
    $("character").value = id;
    try { localStorage.setItem("character", id); } catch (e) {}
    this.listeners.select.forEach((fn) => fn(id));
    return true;
  },

  show(view) {
    for (const v of ["session", "characters"]) {
      $("view-" + v).hidden = v !== view;
      $("nav-" + v).className = v === view ? "on" : "";
    }
  },

  toast(text) {
    const t = document.createElement("div");
    t.className = "toast";
    t.textContent = text;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 2200);
  },
};

function remembered() {
  try { return localStorage.getItem("character"); } catch (e) { return null; }
}

function route() {
  App.show(location.hash === "#characters" ? "characters" : "session");
}

window.addEventListener("hashchange", route);
$("character").addEventListener("change", (e) => App.select(e.target.value));

window.addEventListener("DOMContentLoaded", async () => {
  route();
  App.config = await App.api("GET", "/config");
  App.listeners.config.forEach((fn) => fn(App.config));
  await App.loadCharacters();
});
