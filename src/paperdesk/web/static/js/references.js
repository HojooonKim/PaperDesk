import { h, icon } from "./ui.js";
import { renderMarkdown } from "./markdown.js";
import { t } from "./i18n.js";

// ---------- Bibliography index (built once from pdf.js text content) ----------

var HEADING = /^(?:\d+\.?\s*|[IVX]+\.?\s*)?(?:references|bibliography|references and notes|literature cited|works cited|참고\s*문헌)\s*$/i;
var STOP = /^(?:appendix|appendices|supplementary material|neurips paper checklist|checklist)\b/i;
var APPENDIX_HEAD = /^[A-H](?:\.\d+)*\.?\s+[A-Z][A-Za-z]/;
var NAME = "[A-Z\\u00C0-\\u017F][A-Za-z\\u00C0-\\u017F'’\\-]+";
var AUTHOR_CITE = new RegExp("(" + NAME + ")(?:\\s+(?:et\\s*al\\.?|and\\s+" + NAME + "|&\\s*" + NAME + "))?\\s*,?\\s*\\(?\\s*((?:19|20)\\d{2}[a-z]?)", "g");
var NUMERIC_CITE = /\[\s*(\d{1,4}(?:\s*[,;–\-]\s*\d{1,4})*)\s*\]/g;
var MAX_ENTRY = 1500;

export function normCitation(text) { return String(text || "").replace(/\u00ad/g, "").replace(/\s+/g, " ").trim(); }
function fold(name) { return name.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z]/g, ""); }
function median(values) { var s = values.slice().sort(function (a, b) { return a - b; }); return s.length ? s[Math.floor(s.length / 2)] : 0; }

function toLines(page, number) {
  var lines = [], current = null;
  function flush() {
    if (current && current.text.trim()) {
      current.text = normCitation(current.text);
      var y = current.y;
      current.edge = y > page.height * 0.94 || y < page.height * 0.05;
      lines.push(current);
    }
    current = null;
  }
  page.items.forEach(function (item) {
    if (typeof item.str !== "string") return;
    var x = item.transform[4], y = item.transform[5], size = item.height || Math.abs(item.transform[3]) || 0;
    if (current && item.str && Math.abs(y - current.y) > Math.max(2, current.height * 0.6)) flush();
    if (!current && item.str) current = { page: number, x: x, y: y, height: size, text: "", width: page.width, pageHeight: page.height };
    if (current) {
      current.text += item.str;
      current.x = Math.min(current.x, x);
      current.height = Math.max(current.height, size);
    }
    if (item.hasEOL) flush();
  });
  flush();
  return lines;
}

function firstSurname(body) {
  // first author = text up to the first comma / "and" / sentence end; a period after an initial (J.) is not an end
  var head = body.split(/,|\band\b|&|(?<!\b[A-Z])\.\s+(?=[A-Z][a-z]|\d)/)[0].trim().replace(/\.$/, "");
  var tokens = head.split(/\s+/).filter(Boolean);
  if (!tokens.length) return "";
  var last = tokens[tokens.length - 1];
  if (tokens.length > 1 && /^[A-Z]{1,2}\.?$/.test(last)) return tokens[0];  // "Vaswani A"
  return last.replace(/[^A-Za-z\u00C0-\u017F'’\-]/g, "");
}

export class ReferenceIndex {
  constructor() {
    this.entries = [];
    this.byNumber = new Map();
    this.byAuthorYear = new Map();
    this.mode = "";
    this.start = null;
    this.end = null;
    this.twoColumn = false;
  }

  get ready() { return this.entries.length > 0; }

  // pages: [{width, height, items}] with pdf.js textContent items
  static build(pages) {
    var index = new ReferenceIndex(), lines = [];
    pages.forEach(function (page, i) { lines.push.apply(lines, toLines(page, i + 1)); });
    index.twoColumn = lines.filter(function (l) { return l.x > l.width * 0.45; }).length >= lines.length * 0.2;
    var at = -1;
    for (var i = lines.length - 1; i >= 0; i--) { if (HEADING.test(lines[i].text)) { at = i; break; } }
    if (at < 0) return index;
    var head = lines[at];
    index.start = { page: head.page, top: 1 - head.y / head.pageHeight, right: head.x > head.width * 0.45 };
    var body = [], fontSize = 0;
    for (var j = at + 1; j < lines.length; j++) {
      var line = lines[j];
      if (line.edge || /^\d{1,4}$/.test(line.text)) continue;
      if (body.length > 3 && (STOP.test(line.text) ||
          (APPENDIX_HEAD.test(line.text) && line.text.length < 80 && fontSize && line.height > fontSize * 1.15))) {
        index.end = { page: line.page };
        break;
      }
      body.push(line);
      if (body.length === 10) fontSize = median(body.map(function (l) { return l.height; }));
    }
    index.entries = index.split(body);
    index.entries.forEach(function (entry) {
      if (entry.number != null && !index.byNumber.has(entry.number)) index.byNumber.set(entry.number, entry);
      if (entry.surname && entry.year) {
        [entry.surname + entry.year, entry.surname + entry.year.replace(/[a-z]$/, "")].forEach(function (key) {
          if (!index.byAuthorYear.has(key)) index.byAuthorYear.set(key, entry);
        });
      }
    });
    return index;
  }

  split(lines) {
    var bracket = lines.filter(function (l) { return /^\[\d{1,4}\]/.test(l.text); }).length;
    var numbered = lines.filter(function (l) { return /^\d{1,3}\.\s+\S/.test(l.text); }).length;
    this.mode = bracket >= 3 ? "bracket" : numbered >= 3 ? "numbered" : "author";
    var mode = this.mode, left = {}, indented = {};
    lines.forEach(function (l) {
      var col = l.x > l.width * 0.45 ? 1 : 0;
      left[col] = left[col] == null ? l.x : Math.min(left[col], l.x);
    });
    lines.forEach(function (l) { var col = l.x > l.width * 0.45 ? 1 : 0; if (l.x > left[col] + 4) indented[col] = true; });
    // Some styles separate entries with extra vertical space instead of a hanging indent.
    var gaps = [];
    lines.forEach(function (l, i) {
      var p = lines[i - 1];
      if (p && p.page === l.page && (p.x > p.width * 0.45) === (l.x > l.width * 0.45) && p.y > l.y) gaps.push(p.y - l.y);
    });
    var lineGap = median(gaps);
    var spaced = lineGap > 0 && gaps.filter(function (g) { return g > lineGap * 1.35; }).length >= gaps.length * 0.12;
    function sameColumn(a, b) { return a && a.page === b.page && (a.x > a.width * 0.45) === (b.x > b.width * 0.45) && a.y > b.y; }
    var entries = [], current = null, previous = null, expected = 1;
    lines.forEach(function (l) {
      var col = l.x > l.width * 0.45 ? 1 : 0, starts;
      if (mode === "bracket") starts = /^\[\d{1,4}\]/.test(l.text);
      else if (mode === "numbered") {
        var m = /^(\d{1,3})\.\s/.exec(l.text);
        starts = !!m && (Number(m[1]) === expected || !current);
      } else if (spaced && sameColumn(previous, l)) starts = previous.y - l.y > lineGap * 1.35;
      else if (indented[col] && !spaced) starts = l.x <= left[col] + 2;
      else starts = !previous || (/[.)]$/.test(previous.text) && /^(?:[A-Z\u00C0-\u017F][^\s,]*,|[A-Z][a-z]+\s+[A-Z])/.test(l.text));
      if (starts || !current) {
        current = { lines: [l], text: l.text, page: l.page };
        entries.push(current);
        if (mode === "numbered") expected = parseInt(l.text, 10) + 1;
      } else {
        current.text = /[A-Za-z]-$/.test(current.text) ? current.text.slice(0, -1) + l.text : current.text + " " + l.text;
      }
      previous = l;
    });
    return entries.filter(function (e) {
      // author-year entries always carry a year; this drops stray appendix lines after the list
      return e.text.length >= 12 && e.text.length <= MAX_ENTRY && (mode !== "author" || /\b(?:19|20)\d{2}[a-z]?\b/.test(e.text));
    }).map(function (e, i) {
      var number = null, body = e.text;
      var marker = /^\[(\d{1,4})\]\s*|^(\d{1,3})\.\s+/.exec(body);
      if (marker && mode !== "author") { number = Number(marker[1] || marker[2]); body = body.slice(marker[0].length); }
      var year = /\b((?:19|20)\d{2}[a-z]?)\b/.exec(body.replace(/\d{4}\.\d{4,5}/g, " "));
      return { index: i, number: number, text: e.text, page: e.page, surname: fold(firstSurname(body)), year: year ? year[1] : "" };
    });
  }

  // Click targets for one rendered page: [{rects:[{left,top,right,bottom}], entries, label}]
  hotspotsFor(pageEl, pageNumber) {
    if (!this.ready || this.skipsWholePage(pageNumber)) return [];
    var layer = pageEl.querySelector(".textLayer");
    if (!layer) return [];
    var walker = document.createTreeWalker(layer, NodeFilter.SHOW_TEXT), node, text = "", segments = [], parent = null;
    while ((node = walker.nextNode())) {
      if (text && node.parentNode !== parent) text += " ";
      segments.push({ node: node, start: text.length });
      text += node.data;
      parent = node.parentNode;
    }
    var base = pageEl.getBoundingClientRect(), self = this, hotspots = [], match;
    function locate(offset, isEnd) {
      for (var i = segments.length - 1; i >= 0; i--) {
        var s = segments[i];
        if (isEnd ? s.start < offset : s.start <= offset) return { node: s.node, offset: Math.min(offset - s.start, s.node.data.length) };
      }
      return null;
    }
    function add(start, end, entries, label) {
      if (!entries.length) return;
      var a = locate(start, false), b = locate(end, true);
      if (!a || !b) return;
      var range = document.createRange();
      try { range.setStart(a.node, a.offset); range.setEnd(b.node, b.offset); } catch (error) { return; }
      var rects = Array.prototype.map.call(range.getClientRects(), function (r) {
        return { left: (r.left - base.left) / base.width, top: (r.top - base.top) / base.height,
          right: (r.right - base.left) / base.width, bottom: (r.bottom - base.top) / base.height };
      }).filter(function (r) { return r.right > r.left; });
      if (!rects.length || self.insideBibliography(pageNumber, rects[0])) return;
      hotspots.push({ rects: rects, entries: entries, label: label });
    }
    if (this.mode !== "author") {
      NUMERIC_CITE.lastIndex = 0;
      while ((match = NUMERIC_CITE.exec(text))) {
        var numbers = [];
        match[1].split(/\s*[,;]\s*/).forEach(function (part) {
          var range = part.split(/\s*[–\-]\s*/).map(Number);
          if (range.length === 2 && range[1] >= range[0] && range[1] - range[0] < 30) {
            for (var n = range[0]; n <= range[1]; n++) numbers.push(n);
          } else numbers.push(range[0]);
        });
        var found = numbers.map(function (n) { return self.byNumber.get(n); }).filter(Boolean);
        add(match.index, match.index + match[0].length, found, match[0].replace(/\s+/g, ""));
      }
    }
    AUTHOR_CITE.lastIndex = 0;
    while ((match = AUTHOR_CITE.exec(text))) {
      var entry = this.byAuthorYear.get(fold(match[1]) + match[2]);
      if (entry) add(match.index, match.index + match[0].length, [entry], match[0].replace(/[\s(]+$/, ""));
    }
    return hotspots;
  }

  skipsWholePage(pageNumber) {
    return !!this.start && pageNumber > this.start.page && (!this.end || pageNumber < this.end.page);
  }

  insideBibliography(pageNumber, rect) {
    if (!this.start || pageNumber !== this.start.page) return false;
    var right = rect.left > 0.45;
    if (this.twoColumn && !this.start.right && right) return true;
    if (this.twoColumn && this.start.right !== right) return false;
    return rect.top >= this.start.top - 0.005;
  }
}

// ---------- Hover controller + popover ----------

var SHOW_DELAY = 220, HIDE_DELAY = 140;

export class CitationPreview {
  constructor(reader, app) {
    this.reader = reader;
    this.app = app;
    this.current = null;
    this.popover = null;
    this.onMove = this.onMove.bind(this);
    this.frame = 0;
    var self = this;
    reader.pagesEl.addEventListener("mousemove", this.onMove);
    reader.pagesEl.addEventListener("mouseleave", function () { cancelAnimationFrame(self.frame); self.frame = 0; self.scheduleHide(); });
    reader.pagesEl.addEventListener("scroll", function () { self.hide(); }, { passive: true });
  }

  destroy() { cancelAnimationFrame(this.frame); this.hide(); }

  onMove(event) {
    if (event.buttons || this.reader.area.active) return;
    if (event.target.closest && event.target.closest(".tcol, .layer.over, .page-translation")) {
      cancelAnimationFrame(this.frame); this.frame = 0;
      var ref = event.target.closest(".xref");
      if (ref) this.showForElement(ref, this.reader.translation.resolveRef(ref));
      else if (!this.overPopover) this.scheduleHide();
      return;
    }
    var self = this, x = event.clientX, y = event.clientY, target = event.target;
    if (this.frame) return;
    this.frame = requestAnimationFrame(function () {
      self.frame = 0;
      var pageEl = target.closest && target.closest(".page, .translated-page");
      var hit = pageEl ? self.hitTest(pageEl, x, y) : null;
      if (hit) self.schedule(hit);
      else if (!self.overPopover) self.scheduleHide();
    });
  }

  hitTest(pageEl, x, y) {
    var page = Number(pageEl.closest(".page-row").dataset.page), state = this.reader.pages[page - 1];
    if (!state || !state.hotspots || !state.hotspots.length) return null;
    var box = pageEl.getBoundingClientRect(), px = (x - box.left) / box.width, py = (y - box.top) / box.height;
    var padX = 2 / box.width, padY = 2 / box.height;
    for (var i = 0; i < state.hotspots.length; i++) {
      var spot = state.hotspots[i];
      for (var j = 0; j < spot.rects.length; j++) {
        var r = spot.rects[j], left = r.left != null ? r.left : r[0], top = r.top != null ? r.top : r[1];
        var right = r.right != null ? r.right : r[2], bottom = r.bottom != null ? r.bottom : r[3];
        if (px >= left - padX && px <= right + padX && py >= top - padY && py <= bottom + padY) {
          return { spot: spot, page: page, rect: { left: box.left + left * box.width, top: box.top + top * box.height, bottom: box.top + bottom * box.height } };
        }
      }
    }
    return null;
  }

  // Previews for references inside translation cards (resolved by TranslationController).
  showForElement(el, spot) {
    if (!spot) return;
    var row = el.closest(".page-row"), rect = el.getBoundingClientRect();
    this.schedule({ spot: spot, page: row ? Number(row.dataset.page) : 0, rect: { left: rect.left, top: rect.top, bottom: rect.bottom }, element: el });
  }

  schedule(hit) {
    clearTimeout(this.hideTimer);
    this.hideTimer = null;
    if (this.current && (this.current.spot === hit.spot || (hit.element && this.current.element === hit.element))) return;
    if (this.pendingHit && (this.pendingHit.spot === hit.spot || (hit.element && this.pendingHit.element === hit.element))) return;
    var self = this;
    this.pendingHit = hit;
    clearTimeout(this.showTimer);
    this.showTimer = setTimeout(function () {
      self.pendingHit = null;
      if (!self.reader.alive) return;
      if (window.getSelection && !window.getSelection().isCollapsed) return;
      self.show(hit);
    }, SHOW_DELAY);
  }

  scheduleHide() {
    clearTimeout(this.showTimer);
    this.pendingHit = null;
    if (!this.popover) { this.current = null; return; }
    if (this.hideTimer) return;
    var self = this;
    this.hideTimer = setTimeout(function () { self.hide(); }, HIDE_DELAY);
  }

  hide() {
    clearTimeout(this.showTimer);
    clearTimeout(this.hideTimer);
    this.showTimer = this.hideTimer = null;
    this.pendingHit = null;
    if (this.popover) this.popover.remove();
    this.popover = null;
    this.current = null;
    this.overPopover = false;
  }

  show(hit) {
    this.hide();
    var self = this, content;
    this.current = hit;
    if (hit.spot.kind === "visual") {
      content = this.reader.visuals.previewContent(hit.spot.target, hit.page);
      if (!content) return;
    } else {
      content = [hit.spot.entries.slice(0, 4).map(function (entry) { return self.renderEntry(entry, hit.spot); }),
        hit.spot.entries.length > 4 ? h("div", { class: "cite-more" }, t("외 {n}편", { n: hit.spot.entries.length - 4 })) : null];
    }
    var box = h("div", { class: "cite-pop" + (hit.spot.kind === "visual" ? " visual" : ""), role: "dialog", "aria-label": t("미리보기"),
      onmouseenter: function () { self.overPopover = true; clearTimeout(self.hideTimer); self.hideTimer = null; },
      onmouseleave: function () { self.overPopover = false; self.scheduleHide(); } }, content);
    document.body.append(box);
    this.popover = box;
    this.place();
    box.querySelectorAll("img").forEach(function (img) { img.addEventListener("load", function () { self.place(); }); });
  }

  place() {
    var box = this.popover, hit = this.current;
    if (!box || !hit) return;
    var width = box.offsetWidth, height = box.offsetHeight;
    var left = Math.max(8, Math.min(innerWidth - width - 8, hit.rect.left - 12));
    var top = hit.rect.bottom + 8;
    if (top + height > innerHeight - 8) top = Math.max(8, hit.rect.top - height - 8);
    box.style.left = left + "px";
    box.style.top = top + "px";
  }

  renderEntry(entry, spot) {
    var app = this.app, reader = this.reader, self = this;
    var saved = app.store.findReading(entry.text);
    var label = entry.number != null ? "[" + entry.number + "]" : spot.label;
    var action;
    if (saved && saved.in_library) {
      action = h("button", { class: "btn small", onclick: function () { self.hide(); app.openDocument(saved.document_id); } }, icon("file", 13), t("서재에서 열기"));
    } else if (saved) {
      action = h("button", { class: "btn small added", onclick: function () { self.hide(); app.router.go("/library?folder=reading"); } }, icon("check", 13), t("읽어볼 논문에 있음"));
    } else {
      action = h("button", { class: "btn small primary", onclick: async function (event) {
        var button = event.currentTarget;
        button.disabled = true;
        var item = await app.addToReadingList(entry.text, reader.id);
        if (item) button.replaceWith(h("button", { class: "btn small added", onclick: function () { self.hide(); app.router.go("/library?folder=reading"); } },
          icon("check", 13), t("읽어볼 논문에 추가됨")));
        else button.disabled = false;
      } }, icon("bookmark", 13), t("읽어볼 논문에 추가"));
    }
    var summary = h("div", { class: "cite-summary", hidden: true });
    var explain = h("button", { class: "btn small", onclick: async function () {
      explain.disabled = true;
      explain.textContent = t("찾는 중…");
      summary.hidden = false;
      summary.replaceChildren(h("span", { class: "typing" }, h("i"), h("i"), h("i")));
      self.place();
      try {
        var result = await app.api.post("/api/references/explain", { citation: entry.text });
        var meta = result.metadata;
        var note = result.grounded ? (meta.source === "arxiv" ? t("arXiv 초록 기반") : t("OpenAlex 초록 기반")) : t("초록을 찾지 못해 제목만 보고 썼어요");
        var body = h("div", { class: "md" });
        renderMarkdown(body, result.summary || "");
        summary.replaceChildren(body, h("div", { class: "cite-source" }, note,
          meta && meta.url ? [" · ", h("a", { href: meta.url, target: "_blank", rel: "noreferrer" }, t("원문 정보"))] : null));
        explain.remove();
      } catch (error) {
        summary.replaceChildren(h("span", { class: "error-text" }, error.message));
        explain.disabled = false;
        explain.textContent = t("다시 시도");
      }
      self.place();
    } }, icon("sparkle", 13), t("논문 설명"));
    var arxiv = /(\d{4}\.\d{4,5})/.exec((entry.text.match(/arxiv[^\d]{0,12}\d{4}\.\d{4,5}/i) || [""])[0]);
    var query = entry.text.replace(/^\[\d+\]\s*|^\d+\.\s+/, "").slice(0, 250);
    return h("div", { class: "cite-entry" },
      h("div", { class: "cite-label" }, label, entry.page ? h("span", null, " · " + t("{n}쪽 참고문헌", { n: entry.page })) : null),
      h("div", { class: "cite-text" }, entry.text),
      summary,
      h("div", { class: "cite-actions" }, action, explain,
        arxiv ? h("a", { href: "https://arxiv.org/abs/" + arxiv[1], target: "_blank", rel: "noreferrer" }, "arXiv") : null,
        h("a", { href: "https://scholar.google.com/scholar?q=" + encodeURIComponent(query), target: "_blank", rel: "noreferrer" }, "Scholar")));
  }
}

