import { ApiClient } from "./js/api.js";
import { LibraryStore, SettingsModel } from "./js/store.js";
import { Router } from "./js/router.js";
import { Sidebar } from "./js/sidebar.js";
import { LibraryView } from "./js/library.js";
import { ReaderView } from "./js/reader.js";
import { AssistantPanel } from "./js/assistant.js";
import { BackgroundImport } from "./js/background.js";
import { SettingsView } from "./js/settings.js";
import { ReadingListView } from "./js/reading.js";
import { askText, confirmDialog, h, icon, modKey, toast } from "./js/ui.js";
import { pdfFiles } from "./js/dnd.js";
import { locale, setLocale, t } from "./js/i18n.js";
import { migrateLegacy, pref, setPref } from "./js/prefs.js";
import { shortcutKey, dialogOpen } from "./js/keyboard.js";

var VIEWS = { library: LibraryView, reader: ReaderView, settings: SettingsView };
// Resizable side panes; bounds match the saved-preference validation on the app side.
var PANES = {
  sidebar: { pref: "sidebar_width", css: "--sidebar-width", min: 200, max: 420, fallback: 252, label: "사이드바 너비 조절" },
  assistant: { pref: "assistant_width", css: "--assistant-width", min: 300, max: 640, fallback: 380, label: "AI 도우미 너비 조절" }
};
var MIN_MAIN = 560;  // the reader's side-by-side view needs a page plus a 260px translation column

// Application controller: owns shared state and the actions views call. Views stay dumb.
class App {
  constructor() {
    this.api = new ApiClient();
    this.store = new LibraryStore(this.api);
    this.settings = new SettingsModel(this.api);
    this.background = new BackgroundImport(this);
    this.router = new Router();
    this.shell = document.getElementById("app");
    this.mainEl = document.getElementById("main");
    this.sidebar = new Sidebar(document.getElementById("sidebar"), this);
    this.assistant = new AssistantPanel(document.getElementById("assistant"), this);
    this.view = null;
    this.lastLibrary = "/library";
    this.fileInput = h("input", { type: "file", accept: "application/pdf,.pdf", multiple: true, hidden: true });
    document.body.append(this.fileInput);
    if (pref("sidebar") === "hidden") this.shell.classList.add("sidebar-hidden");
    if (pref("assistant") === "collapsed") this.shell.classList.add("assistant-collapsed");
    this.paneWidths = {};
    this.resizers = Object.keys(PANES).map(function (name) {
      this.setPaneWidth(name, pref(PANES[name].pref, PANES[name].fallback), false);
      return this.resizer(name);
    }, this);
    this.shell.append.apply(this.shell, this.resizers);

    var self = this;
    // A narrow middle card compacts the reader toolbar so the paper title keeps some room.
    new ResizeObserver(function (entries) { self.mainEl.classList.toggle("compact", entries[0].contentRect.width < 680); }).observe(this.mainEl);
    this.router.addEventListener("change", function () { self.render(); });
    this.store.addEventListener("change", function () {
      self.sidebar.render();
      if (self.view && self.view.onStoreChange) self.view.onStoreChange();
    });
    document.addEventListener("keydown", function (event) { self.onShortcut(event); });
    // Dropping a PDF anywhere outside a specific target imports it into the current folder.
    document.addEventListener("dragover", function (event) { event.preventDefault(); });
    document.addEventListener("drop", function (event) {
      event.preventDefault();
      var files = pdfFiles(event.dataTransfer && event.dataTransfer.files);
      if (files.length) self.importFiles(files, self.currentFolder());
    });
  }

  async start() {
    if (location.pathname === "/") this.router.go("/library", true);
    try {
      await Promise.all([this.store.load(), this.settings.initialize()]);
    } catch (error) {
      toast(error.message, true);
    }
    await this.applyLanguage(this.settings.data ? this.settings.data.ui_language : "system", true);
    if (window.paperdeskBoot && window.paperdeskBoot.restoreFailed) {
      toast(t("백업 복원에 실패해 기존 서재를 열었어요. 백업 파일을 다시 확인해 주세요."), true);
    }
    if (!this.settings.data || !this.settings.data.provider) {
      toast(t("설정에서 사용할 AI를 고르면 번역·설명을 쓸 수 있어요."));
      this.router.go("/settings");
    } else if (!this.settings.active().available) {
      toast(t("선택한 AI에 연결할 수 없어요. 설정에서 로그인 상태를 확인해 주세요."), true);
    }
    this.background.fillDetails(this.store.documents);
  }

  // Load the UI catalog, then redraw everything (sidebar, current view, assistant panel).
  async applyLanguage(choice, initial) {
    var before = locale();
    await setLocale(choice || "system");
    document.getElementById("sidebar").setAttribute("aria-label", t("서재"));
    document.getElementById("assistant").setAttribute("aria-label", t("AI 도우미"));
    // Provider texts are localized by the server, so refetch when the language changed
    // (at startup the first load went out before the saved language was known).
    if (!initial || locale() !== before) await this.settings.load();
    this.render();
    if (this.assistant.reader) this.assistant.build();
  }

  render() {
    var route = this.router.route;
    if (route.name === "library") this.lastLibrary = location.pathname + location.search;
    if (this.view && this.view.destroy) this.view.destroy();
    this.mainEl.replaceChildren();
    this.shell.classList.toggle("with-assistant", route.name === "reader");
    var View = route.name === "library" && route.scope === "reading" ? ReadingListView : VIEWS[route.name];
    this.view = new View(this.mainEl, this, route);
    this.sidebar.render();
    this.resizers.forEach(function (handle) { handle.setAttribute("aria-label", t(PANES[handle.dataset.pane].label)); });
  }

  currentFolder() {
    var route = this.router.route;
    if (route.name === "library" && ["all", "recent", "unfiled", "reading"].indexOf(route.scope) < 0) return route.scope;
    return null;
  }

  // ---- layout ----
  sidebarHidden() { return this.shell.classList.contains("sidebar-hidden"); }
  toggleSidebar() {
    this.shell.classList.toggle("sidebar-hidden");
    setPref("sidebar", this.sidebarHidden() ? "hidden" : "shown");
    if (this.view && this.view.render && !(this.view instanceof ReaderView)) this.view.render(false);
    if (this.view instanceof ReaderView) setTimeout(function () { window.dispatchEvent(new Event("resize")); }, 240);
  }
  toggleAssistant() {
    this.shell.classList.toggle("assistant-collapsed");
    setPref("assistant", this.shell.classList.contains("assistant-collapsed") ? "collapsed" : "open");
    setTimeout(function () { window.dispatchEvent(new Event("resize")); }, 240);
  }
  showAssistant() {
    if (this.shell.classList.contains("assistant-collapsed")) this.toggleAssistant();
  }
  paneShown(name) {
    var classes = this.shell.classList;
    return name === "sidebar" ? !classes.contains("sidebar-hidden") : classes.contains("with-assistant") && !classes.contains("assistant-collapsed");
  }
  // Keeps the middle card at least MIN_MAIN wide; save=true stores the width and lets the reader refit its pages.
  setPaneWidth(name, width, save) {
    var spec = PANES[name], other = name === "sidebar" ? "assistant" : "sidebar";
    var room = innerWidth - MIN_MAIN - (this.paneShown(other) ? this.paneWidths[other] || 0 : 0);
    width = Math.round(Math.max(spec.min, Math.min(spec.max, room, Number(width) || spec.fallback)));
    this.paneWidths[name] = width;
    this.shell.style.setProperty(spec.css, width + "px");
    if (save) {
      setPref(spec.pref, width);
      window.dispatchEvent(new Event("resize"));
    }
  }
  // Drag the gap between two cards; arrow keys move it by 16px and double-click restores the default width.
  resizer(name) {
    var self = this, spec = PANES[name];
    var handle = h("div", { class: "pane-resizer", "data-pane": name, role: "separator", "aria-orientation": "vertical", tabindex: "0" });
    function widthAt(x) { return name === "sidebar" ? x + 4 : innerWidth - x - 4; }
    handle.addEventListener("pointerdown", function (event) {
      if (event.button !== 0) return;
      event.preventDefault();
      handle.setPointerCapture(event.pointerId);
      handle.classList.add("active");
      self.shell.classList.add("resizing");
      function move(e) { self.setPaneWidth(name, widthAt(e.clientX), false); }
      function up() {
        handle.removeEventListener("pointermove", move);
        handle.removeEventListener("pointerup", up);
        handle.removeEventListener("pointercancel", up);
        handle.classList.remove("active");
        self.shell.classList.remove("resizing");
        self.setPaneWidth(name, self.paneWidths[name], true);
      }
      handle.addEventListener("pointermove", move);
      handle.addEventListener("pointerup", up);
      handle.addEventListener("pointercancel", up);
    });
    handle.addEventListener("dblclick", function () { self.setPaneWidth(name, spec.fallback, true); });
    handle.addEventListener("keydown", function (event) {
      var step = event.key === "ArrowLeft" ? -16 : event.key === "ArrowRight" ? 16 : 0;
      if (!step) return;
      event.preventDefault();
      self.setPaneWidth(name, self.paneWidths[name] + (name === "sidebar" ? step : -step), true);
    });
    return handle;
  }
  themeChanged() { this.sidebar.render(); }
  backToLibrary() { this.router.go(this.lastLibrary || "/library"); }
  search(query) { this.router.go(query ? "/library?q=" + encodeURIComponent(query) : "/library"); }
  openDocument(id, page) { this.router.go("/reader?id=" + id + (page && page > 1 ? "&page=" + page : "")); }

  // ---- files ----
  pickFiles(folderId) {
    var self = this;
    this.fileInput.value = "";
    this.fileInput.onchange = function () { self.importFiles(pdfFiles(self.fileInput.files), folderId); };
    this.fileInput.click();
  }

  async importFiles(files, folderId) {
    if (!files.length) { toast(t("PDF 파일만 추가할 수 있어요."), true); return; }
    toast(t("{n}개 파일을 추가하는 중…", { n: files.length }));
    var result = await this.store.upload(files, folderId);
    var parts = [];
    if (result.added) parts.push(t("{n}편 추가", { n: result.added }));
    if (result.existing) parts.push(t("{n}편은 이미 있음", { n: result.existing }));
    if (parts.length) toast(parts.join(", "));
    result.failed.forEach(function (message) { toast(message, true); });
    // Details, a folder (only when none was chosen) and, with automatic translation on, the translation, without opening it.
    this.background.add(result.created, !folderId);
  }

  // ---- folders ----
  async newFolder(parentId) {
    var parent = parentId ? this.store.folder(parentId) : null;
    var name = await askText({ title: parent ? t("'{name}' 안에 새 폴더", { name: parent.name }) : t("새 폴더"), placeholder: t("예: Diffusion, 강화학습, 읽을 거리"), confirm: t("만들기") });
    if (!name) return;
    try {
      var folder = await this.store.createFolder(name, parentId);
      this.router.go("/library?folder=" + folder.id);
    } catch (error) { toast(error.message, true); }
  }

  async renameFolder(folder) {
    var name = await askText({ title: t("폴더 이름 바꾸기"), value: folder.name, confirm: t("바꾸기") });
    if (!name || name === folder.name) return;
    try { await this.store.renameFolder(folder.id, name); } catch (error) { toast(error.message, true); }
  }

  async deleteFolder(folder) {
    var count = this.store.countIn(folder.id);
    var ok = await confirmDialog({
      title: t("'{name}' 폴더를 삭제할까요?", { name: folder.name }),
      message: count ? t("안에 있는 논문 {n}편과 하위 폴더는 지워지지 않고 한 단계 위로 옮겨져요.", { n: count }) : t("빈 폴더예요."),
      confirm: t("삭제"), danger: true
    });
    if (!ok) return;
    var parent = folder.parent_id;
    try {
      await this.store.deleteFolder(folder.id);
      if (this.router.route.scope === folder.id) this.router.go(parent ? "/library?folder=" + parent : "/library", true);
    } catch (error) { toast(error.message, true); }
  }

  async moveFolder(id, parentId) {
    if (id === parentId) return;
    try { await this.store.moveFolder(id, parentId); if (parentId) this.store.setExpanded(parentId, true); }
    catch (error) { toast(error.message, true); }
  }

  async moveDocuments(ids, folderId) {
    try {
      for (var i = 0; i < ids.length; i++) await this.api.patch("/api/documents/" + ids[i], { folder_id: folderId || null });
      await this.store.load();
      var folder = folderId ? this.store.folder(folderId) : null;
      toast(t("{n}편을 '{folder}'(으)로 옮겼어요", { n: ids.length, folder: folder ? folder.name : t("분류 안 됨") }));
    } catch (error) { toast(error.message, true); await this.store.load(); }
  }

  // Folder picker: target = {documents: [ids]} or {folder: folder}
  chooseFolderFor(target) {
    var self = this, store = this.store;
    var blocked = target.folder ? store.descendants(target.folder.id) : new Set();
    if (target.folder) blocked.add(target.folder.id);
    var list = h("div", { class: "menu", style: "position:static;box-shadow:none;border:0;background:transparent;max-height:50vh;overflow:auto;padding:0" });
    var backdrop = h("div", { class: "backdrop", onmousedown: function (event) { if (event.target === backdrop) backdrop.remove(); } },
      h("div", { class: "dialog" }, h("h3", null, target.folder ? t("'{name}' 옮기기", { name: target.folder.name }) : t("폴더로 옮기기")), list,
        h("div", { class: "buttons" }, h("button", { class: "btn", onclick: function () { backdrop.remove(); } }, t("취소")))));
    function choose(folderId) {
      backdrop.remove();
      if (target.folder) self.moveFolder(target.folder.id, folderId);
      else self.moveDocuments(target.documents, folderId);
    }
    list.append(h("button", { onclick: function () { choose(null); } }, icon(target.folder ? "books" : "inbox"), target.folder ? t("맨 위") : t("분류 안 됨")));
    (function walk(parentId, depth) {
      store.children(parentId).forEach(function (folder) {
        if (blocked.has(folder.id)) return;
        list.append(h("button", { style: "padding-left:" + (9 + depth * 16) + "px", onclick: function () { choose(folder.id); } }, icon("folder"), folder.name));
        walk(folder.id, depth + 1);
      });
    })(null, 0);
    document.body.append(backdrop);
  }

  // ---- reading list ----
  async addToReadingList(citation, sourceDocId) {
    try {
      var result = await this.store.addReading(citation, sourceDocId);
      toast(result.created ? t("'{title}'을(를) 읽어볼 논문에 추가했어요", { title: result.item.title }) : t("이미 읽어볼 논문에 있어요"));
      return result.item;
    } catch (error) {
      toast(error.message, true);
      return null;
    }
  }

  // ---- documents ----
  async renameDocument(doc) {
    var title = await askText({ title: t("논문 이름 바꾸기"), value: doc.title, confirm: t("바꾸기") });
    if (!title || title === doc.title) return;
    try {
      await this.store.renameDocument(doc.id, title);
      if (this.view instanceof ReaderView) this.view.titleEl.textContent = title;
    } catch (error) { toast(error.message, true); }
  }

  async organizeUnfiled() {
    var docs = this.store.documentsIn("unfiled");
    if (!docs.length) return;
    if (!this.background.ready()) { toast(t("설정에서 사용할 AI를 고르면 번역·설명을 쓸 수 있어요."), true); return; }
    var ok = await confirmDialog({
      title: t("분류 안 된 논문 {n}편을 정리할까요?", { n: docs.length }),
      message: t("연결한 AI가 논문마다 내 폴더 중에서 고르거나, 맞는 폴더가 없으면 새로 만들어요. 한 편에 사용량이 조금 발생해요."),
      confirm: t("정리하기")
    });
    if (!ok) return;
    var moved = 0, failed = [];
    toast(t("{n}편을 정리하는 중…", { n: docs.length }));
    for (var i = 0; i < docs.length; i++) {
      try {
        if (!docs[i].text_pages) await this.background.readText(docs[i].id);  // never opened: the AI reads its first page
        if (this.settings.data.auto_info) await this.background.details(docs[i].id);  // the research area helps choose
        var result = await this.background.organize(docs[i].id);
        if (result.folder) moved++;
      } catch (error) { failed.push(error.message); }
    }
    toast(t("{n}편을 폴더에 정리했어요.", { n: moved }));
    if (failed.length) toast(t("{n}편은 정리하지 못했어요: {message}", { n: failed.length, message: failed[0] }), true);
  }

  async copyBibtex(ids) {
    try {
      var text = (await this.api.post("/api/bibtex", { ids: ids })).bibtex;
      await navigator.clipboard.writeText(text);
      await this.store.load();  // details found just now show up in the list
      toast(t("BibTeX {n}편을 복사했어요", { n: ids.length }));
    } catch (error) { toast(error.message, true); }
  }

  async findDetails(doc) {
    try {
      var found = (await this.api.post("/api/documents/" + doc.id + "/info", { force: true })).document;
      await this.store.load();
      toast(found.authors || found.year ? t("논문 정보를 찾았어요") : t("arXiv와 OpenAlex에서 이 논문을 찾지 못했어요."), !(found.authors || found.year));
    } catch (error) { toast(error.message, true); }
  }

  async deleteDocuments(ids) {
    var single = ids.length === 1 ? this.store.document(ids[0]) : null;
    var ok = await confirmDialog({
      title: single ? t("'{title}'을(를) 삭제할까요?", { title: single.title }) : t("{n}편을 삭제할까요?", { n: ids.length }),
      message: t("PDF와 AI 대화 기록이 이 컴퓨터에서 지워져요."), confirm: t("삭제"), danger: true
    });
    if (!ok) return;
    try {
      for (var i = 0; i < ids.length; i++) {
        await this.api.del("/api/documents/" + ids[i]);  // the chat history goes with it (database cascade)
      }
      await this.store.load();
    } catch (error) { toast(error.message, true); }
  }

  // ---- keyboard ----
  onShortcut(event) {
    if (event.defaultPrevented || event.isComposing || event.altKey || dialogOpen() || !modKey(event)) return;
    var key = shortcutKey(event);
    if (key === "k") { event.preventDefault(); if (this.sidebarHidden()) this.toggleSidebar(); this.sidebar.searchInput.focus(); }
    else if (key === "o") { event.preventDefault(); this.pickFiles(this.currentFolder()); }
    else if (key === ",") { event.preventDefault(); this.router.go("/settings"); }
    else if (key === "\\") { event.preventDefault(); this.toggleSidebar(); }
    else if (key === "j" && this.router.route.name === "reader") { event.preventDefault(); this.toggleAssistant(); }
  }
}

async function start() {
  await migrateLegacy(new ApiClient());
  window.paperdesk = new App();
  window.paperdesk.started = window.paperdesk.start();  // background work waits for this: settings and the AI's status
  await window.paperdesk.started;
}
start().catch(function (error) { toast(error.message, true); });
