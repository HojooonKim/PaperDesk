import { confirmDialog, h, icon, menuAt, toast } from "./ui.js";
import { compact } from "./layout.js";
import { renderInlineMath } from "./markdown.js";
import { AUTHOR_CITE, NUMERIC_CITE } from "./references.js";
import { drawRects, rectContains } from "./textmap.js";
import { t } from "./i18n.js";

var PAGE_MODES = [["compare", "원본과 번역 페이지"], ["translated", "번역만 보기"]];
var MODES = [["side", "나란히"], ["over", "원문 위에"], ...PAGE_MODES, ["off", "번역 숨기기"]];
// Cross-reference words in every UI/answer language we ship (ko, en, ja, zh).
var VISUAL_REF = /(그림|표|알고리즘|アルゴリズム|算法|図|图|表|Figures?|Figs?\.|Tables?|Tabs?\.|Algorithms?|Alg\.)\s*(\d+|[A-Z]\.\d+)|(수식|식|数式|公式|方程|式|Eqs?\.|Equations?)\s*(?:\\\(|\$)?\s*[\(（]?(\d+[a-z]?|[A-Z]\.\d+)[\)）]?\s*(?:\\\)|\$)?/;
var XREF = new RegExp([VISUAL_REF.source, NUMERIC_CITE.source, AUTHOR_CITE.source].join("|"), "g");
var XREF_TABLE = /^(표|表|Tab)/i, XREF_ALGORITHM = /^(알고리즘|アルゴリズム|算法|Alg)/i;

export function showsTranslatedPage(mode) { return mode === "compare" || mode === "translated"; }

// Body translation: cards beside (or over) the PDF, sentence-to-sentence linking, magnifier per paragraph,
// section and whole-paper translation through a queue.
export class TranslationController {
  constructor(reader) {
    this.reader = reader;
    this.app = reader.app;
    this.store = {};
    this.pending = new Set();
    this.submitting = new Set();
    this.requesting = new Set();
    this.running = false;
    this.jobs = [];
    this.done = 0;
    this.total = 0;
    this.active = null;
    var self = this;
    this.label = h("span", null, t("번역"));
    this.button = h("button", { class: "btn tb-btn", title: t("본문 번역"), onclick: function (event) { self.openMenu(event.currentTarget); } },
      icon("translate"), this.label, icon("chevronDown", 12));
    this.pageModes = h("div", { class: "page-modes", role: "group", "aria-label": t("번역 보기"), hidden: true },
      PAGE_MODES.map(function (mode) {
        return h("button", { class: "btn small", type: "button", "data-mode": mode[0],
          onclick: function () { reader.setTranslationMode(mode[0]); } }, t(mode[1]));
      }));
    this.statusText = h("span");
    this.statusAction = h("button", { class: "btn small", hidden: true, onclick: function () { self.reader.startAnalysis(true); } }, t("다시 분석"));
    this.progress = h("progress", { "aria-label": t("본문 번역"), hidden: true });
    this.status = h("div", { class: "translation-status", role: "status", "aria-live": "polite" }, this.statusText, this.progress, this.statusAction);
    this.updateLabel();
    this.hover = h("div", { class: "block-hover" });
    this.hoverButton = h("button", { class: "block-btn", onmousedown: function (event) { event.preventDefault(); }, onclick: function (event) {
      event.stopPropagation();
      self.onHoverButton();
    } });
    this.hover.append(this.hoverButton);
    this.hoverButton.addEventListener("mouseenter", function () {
      cancelAnimationFrame(self.frame); self.frame = 0; clearTimeout(self.hideTimer); self.hideTimer = null;
    });
    this.hoverButton.addEventListener("mouseleave", function () { self.scheduleHideHover(); });
    this.onMove = this.onMove.bind(this);
    reader.pagesEl.addEventListener("mousemove", this.onMove);
    reader.pagesEl.addEventListener("mouseleave", function () { cancelAnimationFrame(self.frame); self.frame = 0; self.clearSentence(); self.scheduleHideHover(); });
    reader.pagesEl.addEventListener("mouseover", function (event) { self.onCardOver(event); });
    reader.pagesEl.addEventListener("mouseout", function (event) { self.onCardOut(event); });
    reader.pagesEl.addEventListener("wheel", function (event) { self.onCardWheel(event); }, { passive: false });
  }

  destroy() { clearTimeout(this.pollTimer); clearTimeout(this.hideTimer); cancelAnimationFrame(this.frame); this.clearSentence(); this.hover.remove(); }

  get analysis() { return this.reader.analysis; }

  updatePageModes() {
    var mode = this.reader.tmode;
    this.pageModes.hidden = !showsTranslatedPage(mode);
    Array.from(this.pageModes.children).forEach(function (button) {
      button.setAttribute("aria-pressed", String(button.dataset.mode === mode));
    });
  }

  async onAnalysis() {
    try {
      var data = await this.app.api.get("/api/documents/" + this.reader.id + "/translations");
      this.language = data.language;
      this.store = data.blocks || {};
    } catch (error) { this.loadFailed = true; this.updateLabel(); console.warn(error); return; }
    if (!await this.pollJobs()) return;
    var reader = this.reader, self = this;
    reader.pages.forEach(function (state) { if (state.rendered) self.renderPage(state); });
    reader.nav.refreshSections();
    var provider = this.app.settings.active();
    if (!this.autoStarted && reader.alive && this.app.settings.data.auto_translate && reader.tmode !== "off" && provider && provider.available &&
        !this.jobs.some(function (job) { return job.language === self.language && job.state !== "completed"; })) {
      this.autoStarted = true;
      var fresh = this.analysis.blocks.filter(function (b) { return b.translatable && !self.store[b.key] && !self.pending.has(b.key); });
      if (fresh.length) await this.enqueue(fresh);
    }
  }

  blocksOn(page) {
    var info = this.analysis && this.analysis.pages[page - 1];
    return info ? info.blocks.filter(function (b) { return b.translatable; }) : [];
  }

  // Blocks with any part on this page (a paragraph continued from the previous column/page included), with that part's rect.
  partsOn(page) {
    if (!this.analysis) return [];
    var out = [];
    this.analysis.blocks.forEach(function (b) {
      if (!b.translatable) return;
      b.parts.forEach(function (part) { if (part.page === page) out.push({ block: b, rect: part.rect }); });
    });
    return out;
  }

  // ---------- menu ----------
  openMenu(anchor) { menuAt(anchor, this.menuItems()); }

  menuItems() {
    var self = this, reader = this.reader;
    var items = [{ title: t("번역 보기") }];
    MODES.forEach(function (mode) {
      items.push({ label: (reader.tmode === mode[0] ? "✓ " : "   ") + t(mode[1]), onClick: function () { reader.setTranslationMode(mode[0]); } });
    });
    items.push("-");
    if (!this.analysis) { items.push({ title: t("문서를 분석하는 중이에요…") }); return items; }
    // Only what can be done now: queued paragraphs are not offered again, nothing is redone while a job runs.
    function open(b) { return !self.store[b.key] && !self.pending.has(b.key); }
    var remaining = this.analysis.blocks.filter(function (b) { return b.translatable && open(b); });
    var page = this.blocksOn(reader.current);
    var mine = this.jobs.filter(function (job) { return job.language === self.language; });
    var interrupted = mine.some(function (job) { return job.state === "failed" || job.state === "paused" || job.state === "cancelled"; });
    if (this.running) items.push({ label: t("번역 멈추기"), icon: "close", onClick: function () { self.cancelJobs(); } });
    mine.filter(function (job) { return job.state === "paused" || job.state === "failed"; }).forEach(function (job) {
      items.push({ label: t("중단된 번역 재개 ({done}/{total})", { done: job.completed, total: job.total }), onClick: function () { self.resumeJob(job); } });
      items.push({ label: t("중단 작업 취소"), onClick: async function () {
        await self.app.api.post("/api/translation-jobs/" + job.id + "/cancel"); await self.pollJobs();
      } });
    });
    if (page.some(open)) items.push({ label: t("현재 쪽 번역"), icon: "file", onClick: function () { self.translatePage(reader.current); } });
    if (remaining.length) {
      items.push({ label: t("목차에서 골라 번역…"), icon: "list", onClick: function () { reader.nav.open("sections"); } });
      items.push({ label: interrupted ? t("새 분석으로 남은 본문 번역…") : t("남은 본문 전체 번역 ({n}문단)", { n: remaining.length }),
        icon: "translate", onClick: function () { self.translateAll(remaining); } });
    } else if (!this.running && !this.pending.size) items.push({ title: t("전체 번역 완료") });
    if (!this.running && page.some(function (b) { return self.store[b.key]; })) {
      items.push({ label: t("현재 쪽 다시 번역…"), onClick: function () { self.retranslatePage(); } });
    }
    return items;
  }

  updateLabel() {
    var starting = this.submitting.size > 0, count = this.analysis ? this.analysis.blocks.filter((b) => b.translatable && this.store[b.key]).length : 0;
    if (starting) this.label.textContent = t("번역 준비 중…");
    else if (this.running) this.label.textContent = t("번역 중 {done}/{total}", { done: this.done, total: this.total });
    else {
      this.label.textContent = count ? t("번역 {n}", { n: count }) : t("번역");
    }
    var busy = starting || this.running, text;
    if (this.reader.analysisError) { text = t("문서 분석을 완료하지 못했어요. 원문은 계속 읽을 수 있어요."); busy = false; }
    else if (this.reader.analysisPhase === "preparing") { text = t("문서 분석 모델을 준비하는 중… 처음에는 다운로드가 필요해요."); busy = true; }
    else if (this.reader.analysisPhase) { text = t("Docling으로 문단과 수식을 분석하는 중…"); busy = true; }
    else if (this.loadFailed) text = t("번역을 불러오지 못했어요. 문서를 다시 열어 주세요.");
    else if (this.pollFailed) text = t("번역 상태를 확인하지 못했어요. 다시 확인하는 중…");
    else if (!this.analysis) { text = t("문서를 분석하는 중이에요…"); busy = true; }
    else if (starting) text = t("번역 준비 중…");
    else if (this.running) {
      text = t("번역 중 {done}/{total}", { done: this.done, total: this.total });
      if (!this.done) text += " · " + t("AI 응답을 기다리는 중…");
    } else {
      var latest = this.jobs.filter(function (job) { return job.language === this.language; }, this).slice(-1)[0];
      if (latest && latest.state === "failed" && latest.missing_keys && latest.missing_keys.length) text = t("응답에서 {n}문단이 빠져 번역이 중단됐어요. 번역 메뉴에서 다시 시작해 주세요.", { n: latest.missing_keys.length });
      else if (latest && (latest.state === "failed" || latest.state === "paused")) text = t("중단된 번역이 있어요. 번역 메뉴에서 재개할 수 있어요.");
      else if (latest && latest.state === "cancelled") text = t("번역이 취소됐어요.");
      else if (count) text = t("번역 완료 {n}문단", { n: count });
      else if (!this.app.settings.data.auto_translate) text = t("자동 번역 꺼짐");
      else if (!this.app.settings.data.provider) text = t("AI가 연결되지 않았어요. 설정에서 사용할 AI를 고르세요.");
      else text = t("번역할 본문이 없어요.");
    }
    this.button.classList.toggle("busy", busy);
    this.status.classList.toggle("busy", busy);
    if (this.statusAction) this.statusAction.hidden = !this.reader.analysisError;
    this.status.hidden = this.reader.tmode === "off" && !busy && !this.pollFailed && !this.reader.analysisError;
    if (this.statusText.textContent !== text) this.statusText.textContent = text;
    this.progress.hidden = !this.running || starting || this.pollFailed;
    this.progress.max = this.total || 1;
    this.progress.value = this.done;
  }

  // ---------- queue ----------
  translatePage(page) {
    var blocks = this.blocksOn(page);
    if (!blocks.length) { toast(t("이 쪽에는 번역할 본문이 없어요.")); return; }
    this.enqueue(blocks);
  }

  translateSection(sectionId) {
    var blocks = this.analysis.blocks.filter(function (b) { return b.translatable && b.sectionId === sectionId; });
    this.enqueue(blocks);
  }

  async translateAll(blocks) {
    var chars = blocks.reduce(function (n, b) { return n + b.text.length; }, 0);
    var ok = await confirmDialog({ title: t("남은 본문을 모두 번역할까요?"), confirm: t("번역 시작"),
      message: t("{n}문단, 약 {k}천 자예요. 연결한 AI의 사용량이나 요금이 그만큼 쓰여요. 이미 번역한 문단은 다시 보내지 않아요.", { n: blocks.length, k: Math.round(chars / 1000) }) });
    if (ok) this.enqueue(blocks);
  }

  async enqueue(blocks, force) {
    if (this.reader.tmode === "off") this.reader.setTranslationMode("side");
    var self = this;
    var fresh = blocks.filter(function (b) { return (force || !self.store[b.key]) && !self.pending.has(b.key); });
    if (!fresh.length) { toast(t("이미 번역했어요.")); return; }
    fresh.forEach(function (b) { self.submitting.add(b.key); self.pending.add(b.key); });
    this.updateLabel();
    this.refreshPages(fresh);
    try {
      await this.app.api.post("/api/documents/" + this.reader.id + "/translation-jobs", {
        blocks: fresh.map(function (b) { return { key: b.key, sentences: b.sentences }; }),
        title: this.reader.title(), terms: this.app.assistant.keyTerms(), force: !!force
      });
    } catch (error) { toast(error.message, true); }
    finally { fresh.forEach(function (b) { self.submitting.delete(b.key); }); }
    await this.pollJobs();
  }

  async pollJobs() {
    clearTimeout(this.pollTimer);
    if (!this.reader.alive) return;
    try {
      var data = await this.app.api.get("/api/documents/" + this.reader.id + "/translation-jobs");
      this.jobs = data.jobs;
      var active = this.jobs.filter(function (j) { return j.language === this.language && (j.state === "queued" || j.state === "running"); }, this);
      this.running = active.length > 0;
      this.done = active.reduce(function (n, j) { return n + j.completed; }, 0);
      this.total = active.reduce(function (n, j) { return n + j.total; }, 0);
      var saved = await this.app.api.get("/api/documents/" + this.reader.id + "/translations");
      if (!this.reader.alive) return;
      this.store = saved.blocks;
      this.pending = new Set(this.submitting);
      this.requesting = new Set();
      this.jobs.filter(function (job) { return job.language === this.language; }, this).forEach(function (job) {
        (job.active_keys || []).forEach(function (key) { this.requesting.add(key); }, this);
      }, this);
      active.forEach(function (job) { (job.pending_keys || []).forEach(function (key) { if (!this.store[key]) this.pending.add(key); }, this); }, this);
      this.pollFailed = false;
      this.updateLabel();
      var self = this;
      this.reader.pages.forEach(function (page) { if (page.rendered) self.renderPage(page); });
      this.reader.nav.refreshSections();
      if (!this.recoveryNotice && this.jobs.some(function (j) { return j.state === "paused" || j.state === "failed"; })) {
        this.recoveryNotice = true;
        toast(t("중단된 번역이 있어요. 번역 메뉴에서 재개할 수 있어요."));
        var failed = this.jobs.find(function (j) { return j.state === "failed"; });
        if (failed) toast(failed.error === "rate_limited" ? t("AI 사용 한도에 도달했어요. 해당 AI에서 한도를 확인한 뒤 다시 시도해 주세요.") :
          failed.error === "auth_required" ? t("AI 로그인이 만료되었거나 필요해요. 해당 CLI에서 다시 로그인한 뒤 연결 시험을 해 주세요.") :
          failed.error === "unsupported_model" ? t("선택한 모델을 사용할 수 없어요. 설치·모델 확인에서 지원 모델을 고르고 연결 시험을 해 주세요.") :
          t("일부 문단의 번역을 받지 못했어요. 다시 시도해 주세요."), true);
      }
    } catch (error) {
      this.pollFailed = true; this.updateLabel(); console.warn(error);
      if (this.reader.alive) this.pollTimer = setTimeout(() => this.pollJobs(), 1200);
      return false;
    }
    if (this.reader.alive && (this.running || this.jobs.some(function (j) { return j.request_in_flight; }))) {
      var self = this;
      this.pollTimer = setTimeout(function () { self.pollJobs(); }, 1200);
    }
    return true;
  }

  async cancelJobs() {
    try {
      for (var job of this.jobs.filter(function (j) { return j.state === "queued" || j.state === "running"; })) {
        await this.app.api.post("/api/translation-jobs/" + job.id + "/cancel");
      }
      toast(t("남은 번역을 취소했어요. 이미 보낸 요청은 완료·저장될 수 있어요."));
      await this.pollJobs();
    } catch (error) { toast(error.message, true); }
  }

  async resumeJob(job) {
    var ok = await confirmDialog({ title: t("번역을 재개할까요?"), confirm: t("재개"),
      message: t("중단 직전에 전송한 요청은 사용량에 이미 반영되었을 수 있어요. 같은 AI·모델·언어로 남은 문단을 다시 요청해요.") });
    if (!ok) return;
    try {
      await this.app.api.post("/api/translation-jobs/" + job.id + "/resume");
      await this.pollJobs();
    } catch (error) { toast(error.message, true); }
  }

  async retranslatePage() {
    var ok = await confirmDialog({ title: t("현재 쪽을 다시 번역할까요?"), confirm: t("다시 번역"),
      message: t("현재 선택한 AI로 새 번역을 요청해요. 사용량이 발생하며 완료한 문단의 기존 번역을 바꿔요.") });
    if (ok) this.enqueue(this.blocksOn(this.reader.current), true);
  }

  refreshPages(blocks) {
    var reader = this.reader, pages = new Set(blocks.map(function (b) { return b.page; }));
    pages.forEach(function (n) { var state = reader.pages[n - 1]; if (state && state.rendered) reader.translation.renderPage(state); });
  }

  // ---------- cards ----------
  onPageRender(state) { this.renderPage(state); }

  clearTranslatedPage(state) {
    if (!state.translatedSource) return;
    var page = state.translatedPage;
    var canvas = page.querySelector("canvas");
    if (canvas) { canvas.width = canvas.height = 0; canvas.remove(); }
    page.querySelector(".page-translations").replaceChildren();
    state.translatedSource = null;
    state.translationDeferred = false;
  }

  renderTranslatedPage(state) {
    if (!showsTranslatedPage(this.reader.tmode) || state.nearViewport === false) return;
    var page = state.translatedPage, source = state.el.querySelector("canvas");
    if (!source.dataset.rendered) return;
    if (state.translatedSource !== source) {
      var canvas = page.querySelector("canvas");
      if (!canvas) { canvas = h("canvas", { "aria-hidden": "true" }); page.prepend(canvas); }
      canvas.width = source.width;
      canvas.height = source.height;
      canvas.getContext("2d").drawImage(source, 0, 0);
      state.translatedSource = source;
    }
    var layer = page.querySelector(".page-translations");
    var selection = window.getSelection();
    if (selection && !selection.isCollapsed && layer.contains(selection.anchorNode)) {
      state.translationDeferred = true;
      return;
    }
    state.translationDeferred = false;
    var info = this.analysis && this.analysis.pages[state.number - 1];
    if (!info) { layer.replaceChildren(); return; }
    var protectedRects = info.blocks.filter((b) => /^(figure|table|algorithm|equation)$/.test(b.kind)).map((b) => b.rect);
    var blocks = this.blocksOn(state.number).filter((b) => {
      if (!this.store[b.key] || b.parts.length !== 1) return false;
      // A detector can give prose and an illustration overlapping boxes. Keep the original in those areas.
      var r = b.rect;
      return !protectedRects.some((p) => Math.min(r[2], p[2]) - Math.max(r[0], p[0]) > 1 / state.size.width &&
        Math.min(r[3], p[3]) - Math.max(r[1], p[1]) > 1 / state.size.height);
    });
    this.syncCards(layer, blocks, true);
    blocks.forEach((block, index) => {
      var card = layer.children[index], r = block.rect;
      var size = Math.max(8, block.size * this.reader.scale);
      var box = [r[0], r[1], r[2] - r[0], r[3] - r[1]].map((n) => n * 100 + "%");
      var geometry = box.join("/") + "/" + size;
      if (card.geometry === geometry) return;
      card.geometry = geometry;
      [card.style.left, card.style.top, card.style.width, card.style.height] = box;
      card.style.fontSize = size + "px";
      var minSize = Math.max(8, size * 0.75);
      while ((card.scrollHeight > card.clientHeight + 1 || card.scrollWidth > card.clientWidth + 1) && size > minSize) {
        size = Math.max(minSize, size * 0.92);
        card.style.fontSize = size + "px";
      }
      if (card.scrollHeight > card.clientHeight + 1 || card.scrollWidth > card.clientWidth + 1) card.tabIndex = 0;
      else card.removeAttribute("tabindex");
    });
  }

  renderPage(state) {
    var mode = this.reader.tmode, self = this;
    var over = state.el.querySelector(".layer.over");
    var scrollTop = state.tcol.scrollTop;
    var selection = window.getSelection();
    if (selection && !selection.isCollapsed && (state.tcol.contains(selection.anchorNode) || over.contains(selection.anchorNode))) {
      state.translationDeferred = true; return;
    }
    state.translationDeferred = false;
    state.el.querySelectorAll(".translation-request").forEach(function (n) { n.remove(); });
    var requesting = this.requesting || new Set();
    this.partsOn(state.number).forEach(function (part) {
      if (requesting.has(part.block.key)) drawRects(state.el.querySelector(".layer.flash"), [part.rect], "translation-request");
    });
    if (showsTranslatedPage(mode)) {
      state.tcol.replaceChildren(); over.replaceChildren();
      this.renderTranslatedPage(state);
      return;
    }
    if (mode === "off" || !this.analysis) { state.tcol.replaceChildren(); over.replaceChildren(); return; }
    var blocks = this.blocksOn(state.number).filter(function (b) { return self.store[b.key] || self.pending.has(b.key); });
    var height = state.el.offsetHeight, width = state.el.offsetWidth;
    if (mode === "side") {
      over.replaceChildren();
      var placed = blocks;
      this.syncCards(state.tcol, placed);
      this.placeCards(state, placed);
      state.tcol.scrollTop = scrollTop;
    } else {
      state.tcol.replaceChildren();
      this.syncCards(over, blocks);
      blocks.forEach(function (block) {
        var card = Array.from(over.children).find(function (c) { return c.dataset.key === block.key; }), r = block.rect;
        card.classList.add("over");
        card.style.cssText = "left:" + r[0] * width + "px;top:" + r[1] * height + "px;width:" + (r[2] - r[0]) * width + "px;height:" + Math.max(14, (r[3] - r[1]) * height) + "px";
        var size = Math.max(8, block.size * self.reader.scale * 0.92);
        card.style.fontSize = size + "px";
        for (var i = 0; i < 10 && card.scrollHeight > card.clientHeight + 1 && size > 6; i++) {
          size *= 0.92;
          card.style.fontSize = size + "px";
        }
      });
    }
  }

  // Polling must leave unchanged nodes in place: selection, hover and preview anchors live on them.
  syncCards(container, blocks, pageText) {
    var previous = new Map(Array.from(container.children).map(function (card) { return [card.dataset.key, card]; })), self = this;
    blocks.forEach(function (block, index) {
      var entry = JSON.stringify([self.store[block.key] || null, !self.store[block.key] && !!(self.requesting && self.requesting.has(block.key))]), card = previous.get(block.key);
      if (!card || card.entry !== entry) { if (card) card.remove(); card = self.card(block, pageText); card.entry = entry; }
      previous.delete(block.key);
      if (container.children[index] !== card) container.insertBefore(card, container.children[index] || null);
    });
    previous.forEach(function (card) { card.remove(); });
  }

  placeCards(state, blocks) {
    if (!this.reader.alive || this.reader.tmode !== "side") return;
    // Cards stack in reading order; aligning them to the source paragraph only left empty gaps.
    var bottom = 0, height = state.el.offsetHeight;
    blocks.forEach(function (block, i) {
      var card = state.tcol.children[i];
      if (!card || card.dataset.key !== block.key) return;
      var top = i ? bottom + 6 : 0;
      card.style.top = top + "px";
      bottom = top + card.offsetHeight;
    });
    state.tcol.style.height = height + "px";
  }

  card(block, pageText) {
    var entry = this.store[block.key], self = this;
    var card = h("div", { class: "tcard kind-" + block.kind + (pageText ? " page-translation" : ""), "data-key": block.key });
    if (!entry) {
      var requesting = this.requesting && this.requesting.has(block.key);
      card.append(h("div", { class: "pending" }, requesting ? h("span", { class: "typing" }, h("i"), h("i"), h("i")) : icon("clock", 13),
        requesting ? t("번역 중") : t("번역 대기 중")));
      return card;
    }
    var body = h("div", { class: "ttext" });
    if (entry.sentences && entry.sentences.length === block.sentences.length) {
      entry.sentences.forEach(function (sentence, index) {
        body.append(self.linkify(h("span", { class: "tsent", "data-s": String(index) }), sentence), " ");
      });
    } else {
      if (!pageText) card.append(h("small", { class: "sub" }, t("문장 대응이 맞지 않아 문단 단위로 표시해요.")));
      body.append(this.linkify(h("span", { class: "tsent whole", "data-s": "all" }), entry.text));
    }
    card.append(body);
    return card;
  }

  // Wrap figure/table/equation/citation mentions so hovering them opens the same previews as in the PDF.
  linkify(span, text) {
    span.append(this.linkText(text));
    return span;
  }

  linkText(text) {
    var span = document.createDocumentFragment(), last = 0, match;
    XREF.lastIndex = 0;
    while ((match = XREF.exec(text))) {
      var author = match[6] && this.reader.references?.authorEntry(match[6], match[7]);
      if (match[6] && !author) continue;
      span.append(renderInlineMath(text.slice(last, match.index), function (part) { return document.createTextNode(part); }));
      var ref = h("span", { class: "xref" }, renderInlineMath(match[0], function (part) { return document.createTextNode(part); }));
      if (match[1]) { ref.dataset.kind = XREF_TABLE.test(match[1]) ? "table" : XREF_ALGORITHM.test(match[1]) ? "algorithm" : "figure"; ref.dataset.label = match[2]; }
      else if (match[3]) { ref.dataset.kind = "equation"; ref.dataset.label = match[4]; }
      else {
        ref.dataset.kind = "cite";
        ref.dataset.label = author ? match[0] : match[5];
        if (author) ref.authorEntry = author;
      }
      span.append(ref);
      last = match.index + match[0].length;
    }
    span.append(renderInlineMath(text.slice(last), function (part) { return document.createTextNode(part); }));
    return span;
  }

  // ---------- sentence linking ----------
  blockFor(key) {
    return this.analysis ? this.analysis.blocks.find(function (b) { return b.key === key; }) : null;
  }

  sentenceRange(block, index) {
    if (index === "all") return [0, compact(block.text).length];
    var start = 0;
    for (var i = 0; i < index; i++) start += compact(block.sentences[i]).length;
    return [start, start + compact(block.sentences[index]).length];
  }

  showSentence(block, index, fromCard) {
    this.clearSentence();
    var range = this.sentenceRange(block, index), reader = this.reader, rects = [];
    var pages = new Set(block.parts.map(function (p) { return p.page; }));
    pages.forEach(function (n) {
      var state = reader.pages[n - 1];
      if (!state || !state.map) return;
      rects.push.apply(rects, drawRects(state.el.querySelector(".layer.flash"), state.map.blockRects(block, range[0], range[1]), "sent-hl"));
    });
    this.activeRects = rects;
    var selector = '.tcard[data-key="' + block.key + '"] .tsent[data-s="' + index + '"]';
    this.activeSpans = Array.prototype.slice.call(this.reader.pagesEl.querySelectorAll(selector));
    this.activeSpans.forEach(function (s) { s.classList.add("active"); });
    this.active = block.key + "#" + index;
    this.activeFromCard = !!fromCard;
    if (!fromCard && this.activeSpans.length) this.revealTranslation(this.activeSpans[0]);
  }

  revealTranslation(span) {
    var column = span.closest(".tcol");
    if (!column) return;
    var box = column.getBoundingClientRect(), viewport = this.reader.pagesEl.getBoundingClientRect();
    var top = Math.max(box.top, viewport.top), bottom = Math.min(box.bottom, viewport.bottom);
    var rects = Array.from(span.getClientRects());
    if (bottom <= top || !rects.length || rects.some(function (r) { return r.bottom > top + 8 && r.top < bottom - 8; })) return;
    column.scrollBy({ top: rects[0].top - top - (bottom - top) / 3, behavior: "smooth" });
  }

  clearSentence() {
    (this.activeRects || []).forEach(function (n) { n.remove(); });
    (this.activeSpans || []).forEach(function (s) { s.classList.remove("active"); });
    this.activeRects = null;
    this.activeSpans = null;
    this.active = null;
  }

  onCardWheel(event) {
    if (event.defaultPrevented || event.ctrlKey || !event.deltaY || Math.abs(event.deltaX) > Math.abs(event.deltaY)) return;
    var column = event.target.closest && event.target.closest(".tcol");
    if (!column) return;
    var end = Math.max(0, column.scrollHeight - column.clientHeight);
    if ((event.deltaY < 0 && column.scrollTop <= 1) || (event.deltaY > 0 && column.scrollTop >= end - 1)) {
      var delta = event.deltaY * (event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? column.clientHeight : 1);
      event.preventDefault();
      this.reader.pagesEl.scrollBy(0, delta);
    }
  }

  onCardOver(event) {
    var span = event.target.closest && event.target.closest(".tsent");
    if (span && !event.target.closest(".xref")) {
      var card = span.closest(".tcard"), block = this.blockFor(card.dataset.key);
      var index = span.dataset.s === "all" ? "all" : Number(span.dataset.s);
      if (block && this.active !== block.key + "#" + index) this.showSentence(block, index, true);
    }
    var ref = event.target.closest && event.target.closest(".xref");
    if (ref) this.reader.citations.showForElement(ref, this.resolveRef(ref));
  }

  onCardOut(event) {
    var ref = event.target.closest && event.target.closest(".xref");
    if (ref && !(event.relatedTarget && ref.contains(event.relatedTarget))) this.reader.citations.scheduleHide();
    var span = event.target.closest && event.target.closest(".tsent");
    var card = span && span.closest(".tcard");
    if (span && !(event.relatedTarget && card.contains(event.relatedTarget))) this.clearSentence();
  }

  resolveRef(ref) {
    var kind = ref.dataset.kind, label = ref.dataset.label, reader = this.reader;
    if (kind === "cite") {
      if (!reader.references || !reader.references.ready) return null;
      var entries = ref.authorEntry ? [ref.authorEntry] : reader.references.numberedEntries(label);
      return entries.length ? { kind: "cite", entries: entries, label: ref.textContent } : null;
    }
    var target = reader.visuals.find(kind, label);
    return target ? { kind: "visual", target: target, label: ref.textContent } : null;
  }

  // ---------- hover on the PDF: sentence link + magnifier ----------
  onMove(event) {
    if (event.buttons || !this.analysis || this.reader.area.active) return;
    var pageEl = event.target.closest && event.target.closest(".page");
    if (!pageEl || event.target.closest(".layer.over, .block-hover")) {
      cancelAnimationFrame(this.frame); this.frame = 0;
      if (event.target.closest && event.target.closest(".block-hover")) { clearTimeout(this.hideTimer); this.hideTimer = null; }
      else this.scheduleHideHover();
      return;
    }
    var x = event.clientX, y = event.clientY, self = this;
    if (this.frame) return;
    this.frame = requestAnimationFrame(function () {
      self.frame = 0;
      var state = self.reader.pages[Number(pageEl.dataset.page) - 1];
      if (!state || !state.map) return;
      var box = pageEl.getBoundingClientRect(), px = (x - box.left) / box.width, py = (y - box.top) / box.height;
      var hit = self.partsOn(state.number).find(function (p) { return rectContains(p.rect, px, py, 34 / box.width, 2 / box.height); });
      var block = hit ? hit.block : null;
      if (hit) self.showHover(state, block, hit.rect); else self.scheduleHideHover();
      // sentence under the pointer, for translated blocks
      var index = state.map.hitTest(x, y);
      if (!block || !self.store[block.key] || self.reader.tmode === "off") {
        if (self.active && !self.activeFromCard) self.clearSentence();
        return;
      }
      var offset = index < 0 ? -1 : state.map.blockOffsetOf(block, index);
      var entry = self.store[block.key], which = "all";
      if (entry.sentences && entry.sentences.length === block.sentences.length) {
        which = self.sentenceAt(state, block, offset, px, py);
      }
      if (self.active !== block.key + "#" + which) self.showSentence(block, which);
    });
  }

  sentenceAt(state, block, offset, x, y) {
    var start = 0, best = Infinity, nearest = 0;
    for (var i = 0; i < block.sentences.length; i++) {
      var end = start + compact(block.sentences[i]).length;
      if (offset >= start && offset < end) return i;
      state.map.blockRects(block, start, end).forEach(function (r) {
        var dx = Math.max(r[0] - x, 0, x - r[2]), dy = Math.max(r[1] - y, 0, y - r[3]), distance = dy * 4 + dx;
        if (distance < best) { best = distance; nearest = i; }
      });
      start = end;
    }
    return best === Infinity ? "all" : nearest;
  }

  showHover(state, block, rect) {
    clearTimeout(this.hideTimer);
    this.hideTimer = null;
    var layer = state.el.querySelector(".layer.ui");
    if (this.hover.parentNode !== layer) layer.append(this.hover);
    var r = rect || block.rect;
    this.hover.style.cssText = "left:" + r[0] * 100 + "%;top:" + r[1] * 100 + "%;width:" + (r[2] - r[0]) * 100 + "%;height:" + (r[3] - r[1]) * 100 + "%";
    this.hoverBlock = block;
    var translated = !!this.store[block.key], pending = this.pending.has(block.key);
    var heading = block.kind === "heading";
    var buttonState = pending ? "pending" : translated ? "translated" : heading ? "heading" : "paragraph";
    if (this.hoverButtonState !== buttonState) {
      this.hoverButton.replaceChildren(pending ? "…" : translated ? icon("check", 13) : heading ? "文" : icon("search", 13));
      this.hoverButtonState = buttonState;
    }
    this.hoverButton.title = pending ? t("번역 중") : translated ? t("번역 보기") : heading ? t("이 절 번역") : t("이 문단 번역");
    this.hoverButton.classList.toggle("done", translated);
    this.hoverButton.classList.toggle("section", heading && !translated);
    this.hover.classList.add("show");
  }

  scheduleHideHover() {
    if (this.hideTimer) return;
    var self = this;
    this.hideTimer = setTimeout(function () { self.hideTimer = null; self.hover.classList.remove("show"); self.hoverBlock = null; }, 140);
  }

  onHoverButton() {
    var block = this.hoverBlock;
    if (!block || this.pending.has(block.key)) return;
    if (this.store[block.key]) {
      if (this.reader.tmode === "off") this.reader.setTranslationMode("side");
      var card = this.reader.pagesEl.querySelector('.tcard[data-key="' + block.key + '"]');
      if (card) {
        card.scrollIntoView({ block: "nearest", behavior: "smooth" });
        card.classList.remove("flash"); void card.offsetWidth; card.classList.add("flash");
      }
      return;
    }
    if (block.kind === "heading") this.translateSection(block.sectionId);
    else this.enqueue([block]);
  }
}
