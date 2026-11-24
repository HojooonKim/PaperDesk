import { h, icon, iconButton, toast } from "./ui.js";
import { t } from "./i18n.js";

// Rectangle selection: drag over a page, then explain (as an image), translate the text inside, highlight, note or ask.
export class AreaSelect {
  constructor(reader) {
    this.reader = reader;
    this.active = false;
    var self = this;
    this.button = iconButton("crop", t("영역 선택 (드래그해 그림·표·수식을 묻기)"), function () { self.active ? self.exit() : self.enter(); }, { class: "icon-btn area-toggle" });
    this.onDown = this.onDown.bind(this);
    reader.pagesEl.addEventListener("mousedown", this.onDown);
  }

  destroy() { this.removeMenu(); }

  enter() {
    this.active = true;
    this.reader.readerEl.classList.add("area-mode");
    this.button.classList.add("on");
    toast(t("PDF 위에서 드래그해 영역을 고르세요. Esc로 끝내요."));
  }

  exit() {
    if (!this.active) return;
    this.active = false;
    this.reader.readerEl.classList.remove("area-mode");
    this.button.classList.remove("on");
    this.removeMenu();
  }

  onDown(event) {
    if (!this.active || event.button !== 0) return;
    var pageEl = event.target.closest(".page");
    if (!pageEl) return;
    event.preventDefault();
    this.removeMenu();
    var base = pageEl.getBoundingClientRect(), startX = event.clientX, startY = event.clientY, self = this;
    var box = h("div", { class: "area-box" });
    pageEl.querySelector(".layer.ui").append(box);
    function rectFrom(x, y) {
      var l = (Math.min(startX, x) - base.left) / base.width, t = (Math.min(startY, y) - base.top) / base.height;
      var r = (Math.max(startX, x) - base.left) / base.width, b = (Math.max(startY, y) - base.top) / base.height;
      return [Math.max(0, l), Math.max(0, t), Math.min(1, r), Math.min(1, b)];
    }
    function move(e) {
      var r = rectFrom(e.clientX, e.clientY);
      box.style.cssText = "left:" + r[0] * 100 + "%;top:" + r[1] * 100 + "%;width:" + (r[2] - r[0]) * 100 + "%;height:" + (r[3] - r[1]) * 100 + "%";
    }
    function up(e) {
      document.removeEventListener("mousemove", move);
      document.removeEventListener("mouseup", up);
      var r = rectFrom(e.clientX, e.clientY);
      if ((r[2] - r[0]) * base.width < 10 || (r[3] - r[1]) * base.height < 10) { box.remove(); return; }
      self.box = box;
      self.showMenu(Number(pageEl.dataset.page), r, box.getBoundingClientRect());
    }
    document.addEventListener("mousemove", move);
    document.addEventListener("mouseup", up);
  }

  textIn(page, rect) {
    var info = this.reader.analysis && this.reader.analysis.pages[page - 1];
    if (!info) return "";
    var lines = [];
    info.lines.forEach(function (line) {
      var words = line.runs.filter(function (run) {
        var cx = (run.rect[0] + run.rect[2]) / 2, cy = (run.rect[1] + run.rect[3]) / 2;
        return cx >= rect[0] && cx <= rect[2] && cy >= rect[1] && cy <= rect[3];
      }).map(function (run) { return run.str; });
      if (words.length) lines.push(words.join(" ").replace(/\s+/g, " ").trim());
    });
    return lines.join("\n");
  }

  showMenu(page, rect, anchor) {
    var reader = this.reader, app = reader.app, self = this, text = this.textIn(page, rect);
    var info = { text: text || t("(글자 없음)"), page: page, rects: [rect], rect: anchor };
    function act(fn) { return function () { self.removeMenu(); fn(); }; }
    this.menu = h("div", { class: "selection-menu", role: "toolbar" },
      h("button", { onclick: act(async function () {
        var image = await reader.cropImage(page, rect, 1600);
        app.assistant.runVisual({ task: "region", text: text, context: reader.pageText(page).slice(0, 4000), images: [image], thumb: image,
          label: t("선택 영역"), page: page });
      }) }, icon("sparkle"), t("설명")),
      text ? h("button", { onclick: act(function () { app.assistant.runOnSelection("translate", info); }) }, icon("translate"), t("번역")) : null,
      h("button", { onclick: act(async function () {
        var image = await reader.cropImage(page, rect, 1600);
        app.assistant.quote(Object.assign({}, info, { text: text || t("선택 영역"), image: image }));
      }) }, icon("question"), t("질문")),
      h("button", { onclick: act(function () { reader.annotations.create(info, "highlight"); }) }, icon("highlighter"), t("표시")),
      h("button", { onclick: act(function () { reader.annotations.createNote(info); }) }, icon("note"), t("메모")),
      text ? h("button", { title: t("영역 글자 복사"), onclick: act(function () { navigator.clipboard.writeText(text); toast(t("복사했어요")); }) }, icon("copy")) : null);
    this.menu.addEventListener("mousedown", function (e) { e.preventDefault(); e.stopPropagation(); });
    document.body.append(this.menu);
    reader.placeMenu(this.menu, anchor);
  }

  removeMenu() {
    if (this.menu) { this.menu.remove(); this.menu = null; }
    if (this.box) { this.box.remove(); this.box = null; }
  }
}

