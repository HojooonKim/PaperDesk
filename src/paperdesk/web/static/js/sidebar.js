import { h, icon, iconButton, menuAt, MOD } from "./ui.js";
import { FOLDER_TYPE, makeDropTarget } from "./dnd.js";
import { t } from "./i18n.js";

var THEME_ICONS = { system: "monitor", dark: "moon", light: "sun" };
var THEME_NEXT = { system: "dark", dark: "light", light: "system" };
var THEME_LABEL = { system: "시스템 연동", dark: "다크", light: "라이트" };

export class Sidebar {
  constructor(root, app) {
    this.root = root;
    this.app = app;
    this.searchValue = "";
  }

  render() {
    var app = this.app, route = app.router.route, self = this;
    var input = h("input", {
      type: "search", placeholder: t("논문 검색"), value: route.name === "library" ? route.query : this.searchValue,
      "aria-label": t("논문 검색"),
      onkeydown: function (event) {
        if (event.key === "Enter" && !event.isComposing) app.search(input.value.trim());
        if (event.key === "Escape") { input.value = ""; app.search(""); input.blur(); }
      },
      oninput: function () { self.searchValue = input.value; }
    });
    this.searchInput = input;

    var nav = h("div", null,
      this.navItem("books", t("모든 논문"), app.store.documents.length, route.name === "library" && route.scope === "all" && !route.query,
        function () { app.router.go("/library"); }, null, "all"),
      this.navItem("clock", t("최근에 연 논문"), null, route.name === "library" && route.scope === "recent",
        function () { app.router.go("/library?folder=recent"); }),
      this.navItem("bookmark", t("읽어볼 논문"), app.store.readingList.filter(function (i) { return !i.in_library; }).length || null,
        route.name === "library" && route.scope === "reading", function () { app.router.go("/library?folder=reading"); }),
      this.navItem("inbox", t("분류 안 됨"), app.store.documentsIn("unfiled").length, route.name === "library" && route.scope === "unfiled",
        function () { app.router.go("/library?folder=unfiled"); }, null, "unfiled"));

    var tree = h("div", { role: "tree" });
    this.renderFolders(tree, null, 0, route);

    var themeChoice = window.paperdeskTheme.get();
    this.root.replaceChildren(
      h("div", { class: "sb-head" },
        h("div", { class: "brand" }, h("img", { class: "brand-mark", src: "/brand-mark.png", alt: "", draggable: "false" }), "PaperDesk"),
        iconButton("upload", t("PDF 가져오기 ({key})", { key: MOD + "O" }), function () { app.pickFiles(app.currentFolder()); }),
        iconButton("sidebar", t("사이드바 숨기기 ({key})", { key: MOD + "\\" }), function () { app.toggleSidebar(); })),
      h("label", { class: "search" }, icon("search", 14), input, h("kbd", null, MOD + "K")),
      h("div", { class: "sb-scroll" },
        nav,
        h("div", { class: "sb-label" }, t("폴더"),
          iconButton("folderPlus", t("새 폴더"), function () { app.newFolder(null); })),
        tree,
        app.store.folders.length ? null : h("div", { style: "padding:4px 8px;color:var(--text-3);font-size:12px" }, t("주제별 폴더를 만들어 논문을 정리하세요."))),
      h("div", { class: "sb-foot" },
        h("button", { class: "nav-item" + (route.name === "settings" ? " active" : ""), onclick: function () { app.router.go("/settings"); } },
          icon("settings"), h("span", { class: "label" }, t("설정"))),
        iconButton(THEME_ICONS[themeChoice], t("테마: {name}", { name: t(THEME_LABEL[themeChoice]) }), function () {
          window.paperdeskTheme.set(THEME_NEXT[themeChoice]);
          self.render();
          app.themeChanged();
        })));
  }

  navItem(iconName, label, count, active, onClick, extra, dropScope) {
    var item = h("button", Object.assign({ class: "nav-item" + (active ? " active" : ""), onclick: onClick }, extra || {}),
      h("span", { class: "twisty leaf" }), icon(iconName), h("span", { class: "label" }, label),
      count == null ? null : h("span", { class: "count" }, count));
    if (dropScope) makeDropTarget(item, this.app, null);
    return item;
  }

  renderFolders(container, parentId, depth, route) {
    var self = this, app = this.app, store = app.store;
    store.children(parentId).forEach(function (folder) {
      var kids = store.children(folder.id);
      var open = store.isExpanded(folder.id);
      var twisty = h("span", {
        class: "twisty" + (kids.length ? "" : " leaf") + (open ? " open" : ""),
        onclick: function (event) { event.stopPropagation(); store.setExpanded(folder.id, !open); }
      }, icon("chevron", 12));
      var row = h("button", {
        class: "nav-item" + (route.name === "library" && route.scope === folder.id ? " active" : ""),
        role: "treeitem", "aria-expanded": kids.length ? String(open) : null, draggable: "true",
        style: "padding-left:" + (8 + depth * 14) + "px",
        onclick: function () { app.router.go("/library?folder=" + folder.id); },
        oncontextmenu: function (event) { event.preventDefault(); menuAt(row, self.folderMenu(folder)); },
        ondragstart: function (event) {
          event.dataTransfer.setData(FOLDER_TYPE, folder.id);
          event.dataTransfer.effectAllowed = "move";
        }
      }, twisty, icon("folder"), h("span", { class: "label" }, folder.name), h("span", { class: "count" }, store.countIn(folder.id) || ""),
        h("span", { class: "more icon-btn", style: "width:20px;height:20px", title: t("폴더 메뉴"),
          onclick: function (event) { event.stopPropagation(); menuAt(event.currentTarget, self.folderMenu(folder)); } }, icon("more", 14)));
      makeDropTarget(row, app, folder.id);
      container.append(row);
      if (open && kids.length) self.renderFolders(container, folder.id, depth + 1, route);
    });
  }

  folderMenu(folder) {
    var app = this.app;
    return [
      { label: t("하위 폴더 만들기"), icon: "folderPlus", onClick: function () { app.newFolder(folder.id); } },
      { label: t("이 폴더로 PDF 가져오기"), icon: "upload", onClick: function () { app.pickFiles(folder.id); } },
      { label: t("이름 바꾸기"), icon: "pencil", onClick: function () { app.renameFolder(folder); } },
      { label: t("다른 폴더로 옮기기"), icon: "move", onClick: function () { app.chooseFolderFor({ folder: folder }); } },
      app.store.countIn(folder.id) ? { label: t("BibTeX 복사 (하위 폴더 포함)"), icon: "copy", onClick: function () {
        var wanted = app.store.descendants(folder.id).add(folder.id);
        app.copyBibtex(app.store.documents.filter(function (d) { return wanted.has(d.folder_id); }).map(function (d) { return d.id; }));
      } } : null,
      "-",
      { label: t("폴더 삭제"), icon: "trash", danger: true, onClick: function () { app.deleteFolder(folder); } }
    ].filter(Boolean);
  }
}

