import { h, icon, iconButton, menuAt, showMenu, relativeTime, toast } from "./ui.js";
import { DOC_TYPE, FOLDER_TYPE, hasFiles, makeDropTarget, pdfFiles } from "./dnd.js";
import { t } from "./i18n.js";

var SCOPE_TITLES = { all: "모든 논문", recent: "최근에 연 논문", unfiled: "분류 안 됨" };

// "Vaswani et al. · 2017 · Neural Information Processing Systems", or "" before the details are found.
export function paperDetails(doc) {
  var names = doc.authors ? doc.authors.split(",") : [];
  var first = names.length ? names[0].trim().split(/\s+/).pop() : "";
  return [names.length > 1 ? t("{name} 외", { name: first }) : first, doc.year, doc.venue].filter(Boolean).join(" · ");
}

export class LibraryView {
  constructor(root, app, route) {
    this.root = root;
    this.app = app;
    this.route = route;
    this.selected = new Set();
    this.alive = true;
    this.activity = { translations: [], analysis: [] };
    this.render();
    this.pollActivity();
  }

  destroy() { this.alive = false; clearTimeout(this.activityTimer); }

  async pollActivity() {
    try {
      var data = await this.app.api.get("/api/activity");
      if (!this.alive) return;
      this.activity = data;
      this.progressCells.forEach((cell, id) => { var text = this.progressText(id); if (cell.textContent !== text) cell.textContent = text; });
    } catch (error) { console.warn(error); }
    if (this.alive) this.activityTimer = setTimeout(() => this.pollActivity(), 1500);
  }

  progressText(id) {
    var phase = this.activity.analysis.find((a) => a.doc_id === id);
    if (phase && phase.state === "queued") return t("문서 분석 대기 중");
    if (phase && phase.state === "preparing") return t("문서 분석 모델 준비 중…");
    if (phase && phase.state === "running") return t("문서 분석 중…");
    if (phase && phase.state === "failed") return t("문서 분석 실패 · 열어서 다시 시도");
    var jobs = this.activity.translations.filter((j) => j.doc_id === id);
    var active = jobs.filter((j) => j.state === "queued" || j.state === "running");
    if (active.length) return t("번역 중 {done}/{total}", { done: active.reduce((n, j) => n + j.completed, 0), total: active.reduce((n, j) => n + j.total, 0) });
    var job = jobs.slice(-1)[0];
    if (job && job.state === "completed") return t("번역 완료 {n}문단", { n: job.completed });
    if (job && (job.state === "failed" || job.state === "paused")) return t("번역 중단 {done}/{total} · 열어서 재개", { done: job.completed, total: job.total });
    if (job && job.state === "cancelled") return t("번역이 취소됐어요.");
    if (!this.app.settings.data) return t("AI 연결 상태를 확인하는 중…");
    if (!this.app.settings.data.auto_translate) return t("자동 번역 꺼짐");
    return t("열면 분석 후 자동 번역");
  }

  onStoreChange() { this.render(); }

  get folderId() {
    var scope = this.route.scope;
    return SCOPE_TITLES[scope] ? null : scope;
  }

  render() {
    var app = this.app, store = app.store, route = this.route, self = this;
    var folder = this.folderId ? store.folder(this.folderId) : null;
    this.progressCells = new Map();
    if (this.folderId && !folder) { app.router.go("/library", true); return; }

    var title;
    if (route.query) title = h("h1", null, t("검색: {q}", { q: route.query }));
    else if (folder) {
      title = h("div", { class: "crumbs" }, store.path(folder.id).map(function (item, index, all) {
        var last = index === all.length - 1;
        return [index ? icon("chevron", 12) : null,
          last ? h("h1", null, item.name) : h("button", { onclick: function () { app.router.go("/library?folder=" + item.id); } }, item.name)];
      }));
    } else title = h("h1", null, t(SCOPE_TITLES[route.scope] || t("모든 논문")));

    var toolbar = h("div", { class: "toolbar" },
      app.sidebarHidden() ? iconButton("sidebar", t("사이드바 보이기"), function () { app.toggleSidebar(); }) : null,
      title,
      h("span", { class: "spacer" }),
      folder ? h("button", { class: "btn", onclick: function () { app.newFolder(folder.id); } }, icon("folderPlus"), t("하위 폴더")) : null,
      route.scope === "all" && !route.query ? h("button", { class: "btn", onclick: function () { app.newFolder(null); } }, icon("folderPlus"), t("새 폴더")) : null,
      route.scope === "unfiled" && !route.query && store.documentsIn("unfiled").length && app.background.ready()
        ? h("button", { class: "btn", title: t("연결한 AI가 논문마다 알맞은 폴더를 골라요"), onclick: function () { app.organizeUnfiled(); } }, icon("sparkle"), t("자동 정리")) : null,
      h("button", { class: "btn primary", onclick: function () { app.pickFiles(self.folderId); } }, icon("upload"), t("PDF 가져오기")));

    var body = h("div", { class: "library", "data-drop": t("여기에 PDF를 놓으면 이 폴더에 추가돼요") });
    this.attachFileDrop(body);
    if (route.query) this.renderSearch(body);
    else this.renderTable(body, folder);
    var automatic = app.settings.data && app.settings.data.auto_translate;
    var active = app.settings.active();
    var status = h("div", { class: "translation-status" }, icon("translate", 14),
      h("span", null, !app.settings.data ? t("AI 연결 상태를 확인하는 중…") : automatic ? t("자동 번역 켜짐 · 논문을 열면 분석 후 번역해요.") : t("자동 번역 꺼짐 · 번역 메뉴에서 직접 시작할 수 있어요.")),
      active ? h("span", { class: "sub" }, active.label + (active.model ? " · " + active.model : "")) : null,
      h("button", { class: "btn small", onclick: function () { app.router.go("/settings"); } }, t("설정")));
    this.root.replaceChildren(toolbar, status, body);
  }

  attachFileDrop(body) {
    var self = this;
    body.addEventListener("dragover", function (event) {
      if (!hasFiles(event)) return;
      event.preventDefault();
      body.classList.add("dropzone");
    });
    body.addEventListener("dragleave", function (event) {
      if (!body.contains(event.relatedTarget)) body.classList.remove("dropzone");
    });
    body.addEventListener("drop", function (event) {
      body.classList.remove("dropzone");
      if (!hasFiles(event)) return;
      event.preventDefault();
      event.stopPropagation();
      self.app.importFiles(pdfFiles(event.dataTransfer.files), self.folderId);
    });
  }

  renderTable(body, folder) {
    var app = this.app, store = app.store, self = this;
    var subfolders = folder ? store.children(folder.id) : [];
    var docs = store.documentsIn(this.route.scope);
    if (!subfolders.length && !docs.length) {
      body.append(this.emptyState(folder));
      return;
    }
    var showFolderColumn = !folder;
    var tbody = h("tbody");
    subfolders.forEach(function (child) {
      var row = h("tr", {
        class: "row", draggable: "true",
        ondblclick: function () { app.router.go("/library?folder=" + child.id); },
        ondragstart: function (event) { event.dataTransfer.setData(FOLDER_TYPE, child.id); },
        oncontextmenu: function (event) { event.preventDefault(); showMenu(event.clientX, event.clientY, app.sidebar.folderMenu(child)); }
      },
        h("td", { class: "title" }, h("div", { class: "doc-title" }, icon("folder"), h("span", null, child.name))),
        showFolderColumn ? h("td") : null,
        h("td", null, t("{n}편", { n: store.countIn(child.id) })), h("td"), h("td"), h("td"),
        h("td", { class: "actions" }, iconButton("more", t("폴더 메뉴"), function (event) { menuAt(event.currentTarget, app.sidebar.folderMenu(child)); })));
      makeDropTarget(row, app, child.id);
      tbody.append(row);
    });
    docs.forEach(function (doc) {
      var progress = h("td", { class: "document-progress", role: "status" }, self.progressText(doc.id));
      self.progressCells.set(doc.id, progress);
      var where = doc.folder_id ? store.path(doc.folder_id).map(function (f) { return f.name; }).join(" / ") : t("분류 안 됨");
      var details = paperDetails(doc);
      var row = h("tr", {
        class: "row" + (details ? " tall" : "") + (self.selected.has(doc.id) ? " selected" : ""), draggable: "true", tabindex: "0",
        onclick: function (event) { self.select(doc.id, event); },
        ondblclick: function () { app.openDocument(doc.id); },
        onkeydown: function (event) { if (event.key === "Enter") app.openDocument(doc.id); },
        oncontextmenu: function (event) {
          event.preventDefault();
          if (!self.selected.has(doc.id)) self.select(doc.id, {});
          showMenu(event.clientX, event.clientY, self.documentMenu(doc));
        },
        ondragstart: function (event) {
          var ids = self.selected.has(doc.id) ? Array.from(self.selected) : [doc.id];
          event.dataTransfer.setData(DOC_TYPE, ids.join(","));
          event.dataTransfer.effectAllowed = "move";
          row.classList.add("dragging");
        },
        ondragend: function () { row.classList.remove("dragging"); }
      },
        h("td", { class: "title", title: doc.authors ? doc.title + "\n" + doc.authors : doc.title },
          h("div", { class: "doc-title" }, icon("file"), h("span", null, doc.title)),
          details ? h("div", { class: "meta-line" }, details) : null),
        showFolderColumn ? h("td", null, h("span", { class: "chip", title: where }, where)) : null,
        h("td", null, doc.page_count ? t("{n}쪽", { n: doc.page_count }) : "—"),
        progress,
        h("td", null, relativeTime(doc.last_opened_at)),
        h("td", null, relativeTime(doc.created_at)),
        h("td", { class: "actions" }, iconButton("more", t("논문 메뉴"), function (event) {
          event.stopPropagation();
          menuAt(event.currentTarget, self.documentMenu(doc));
        })));
      tbody.append(row);
    });
    body.append(h("table", { class: "table" },
      h("thead", null, h("tr", null, h("th", null, t("제목")), showFolderColumn ? h("th", null, t("폴더")) : null,
        h("th", null, t("분량")), h("th", null, t("진행 상황")), h("th", null, t("마지막으로 읽음")), h("th", null, t("추가함")), h("th"))),
      tbody));
  }

  select(id, event) {
    if (event.metaKey || event.ctrlKey) {
      if (this.selected.has(id)) this.selected.delete(id); else this.selected.add(id);
    } else {
      this.selected = new Set([id]);
    }
    this.render();
  }

  documentMenu(doc) {
    var app = this.app, ids = this.selected.has(doc.id) ? Array.from(this.selected) : [doc.id];
    var many = ids.length > 1;
    return [
      many ? { title: t("{n}편 선택됨", { n: ids.length }) } : { label: t("열기"), icon: "file", onClick: function () { app.openDocument(doc.id); } },
      many ? null : { label: t("이름 바꾸기"), icon: "pencil", onClick: function () { app.renameDocument(doc); } },
      { label: t("폴더로 옮기기…"), icon: "move", onClick: function () { app.chooseFolderFor({ documents: ids }); } },
      { label: many ? t("BibTeX {n}편 복사", { n: ids.length }) : t("BibTeX 복사"), icon: "copy", onClick: function () { app.copyBibtex(ids); } },
      many ? null : { label: t("논문 정보 다시 찾기"), icon: "search", onClick: function () { app.findDetails(doc); } },
      "-",
      { label: many ? t("{n}편 삭제", { n: ids.length }) : t("삭제"), icon: "trash", danger: true, onClick: function () { app.deleteDocuments(ids); } }
    ].filter(Boolean);
  }

  emptyState(folder) {
    var app = this.app, self = this;
    var scope = this.route.scope;
    var message = scope === "recent" ? t("논문을 열면 여기에 모여요.") :
      scope === "unfiled" ? t("폴더에 넣지 않은 논문이 여기에 보여요.") :
      folder ? t("PDF를 이 창에 끌어다 놓거나 가져오기를 누르면 '{name}' 폴더에 들어가요.", { name: folder.name }) :
      t("PDF를 이 창에 끌어다 놓거나 가져오기를 눌러 첫 논문을 추가하세요.");
    return h("div", { class: "empty-state" }, h("div", null,
      h("div", { class: "art" }, icon(folder ? "folder" : "books")),
      h("h2", null, folder ? t("빈 폴더") : scope === "recent" ? t("아직 연 논문이 없어요") : t("논문이 없어요")),
      h("p", null, message),
      scope === "recent" ? null : h("button", { class: "btn primary", onclick: function () { app.pickFiles(self.folderId); } }, icon("upload"), t("PDF 가져오기"))));
  }

  async renderSearch(body) {
    var app = this.app, query = this.route.query, needle = query.toLowerCase();
    var titleHits = app.store.documents.filter(function (d) { return d.title.toLowerCase().indexOf(needle) >= 0; });
    var box = h("div", { class: "search-results" }, h("div", { class: "loading" }, t("찾는 중…")));
    body.append(box);
    var textHits = [];
    try { textHits = (await app.api.get("/api/search?q=" + encodeURIComponent(query))).results; }
    catch (error) { toast(error.message, true); }
    var items = [];
    titleHits.forEach(function (doc) {
      items.push(h("button", { class: "hit", onclick: function () { app.openDocument(doc.id); } }, h("b", null, doc.title), h("small", null, t("제목 일치"))));
    });
    textHits.forEach(function (hit) {
      items.push(h("button", { class: "hit", onclick: function () { app.openDocument(hit.doc_id, hit.page); } },
        h("b", null, hit.title + " · " + t("{n}쪽", { n: hit.page })), h("small", null, hit.snippet)));
    });
    box.replaceChildren.apply(box, items.length ? items : [h("div", { class: "loading" }, t("'{q}'와 일치하는 논문이 없어요. 본문 검색은 한 번 연 논문만 가능해요.", { q: query }))]);
  }
}

