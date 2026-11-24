import { h, icon, iconButton, toast, MOD } from "./ui.js";
import { renderMarkdown } from "./markdown.js";
import { t } from "./i18n.js";

var TASK_LABEL = { translate: "번역", explain: "설명", ask: "질문", summarize: "요약", define: "뜻", figure: "그림 설명", equation: "수식 설명", region: "영역 설명" };
var MAX_TURNS = 80, PAPER_LIMIT = 60000;
var TABS = [["chat", "대화"], ["digest", "요약"], ["notes", "메모"]];

// Right-hand panel: per-paper conversation, paper digest (3-line summary, key terms, full summary) and highlights/notes.
export class AssistantPanel {
  constructor(root, app) {
    this.root = root;
    this.app = app;
    this.reader = null;
    this.turns = [];
    this.histories = new Map();
    this.pendingAnswers = new WeakMap();
    this.quoted = null;
    this.tab = "chat";
    this.digest = {};
    this.modelChoices = {};
    this.modelCatalogs = {};
    var self = this;
    app.settings.addEventListener("change", function () { if (self.reader) self.renderHead(); });
  }

  attach(reader) {
    if (this.unsubscribe) this.unsubscribe();
    this.unsubscribe = null;
    this.reader = reader;
    this.quoted = null;
    this.digest = {};
    if (!reader) { this.root.replaceChildren(); return; }
    this.history = this.historyFor(reader.id);
    this.turns = this.history.turns;
    var history = this.history;
    history.ready.then(() => {
      if (this.reader !== reader) return;
      this.renderBody();
      this.renderHead();
    });
    var self = this;
    this.unsubscribe = reader.annotations.onChange(function () { if (self.tab === "notes") self.renderBody(); });
    this.build();
  }

  // Chat history is kept per paper in the app's database (GET/PUT /api/documents/<id>/conversation).
  historyFor(id) {
    if (this.histories.has(id)) return this.histories.get(id);
    var history = { id: id, turns: [], writes: Promise.resolve() }, self = this;
    this.histories.set(id, history);
    history.ready = this.app.api.get("/api/documents/" + id + "/conversation").then(function (result) {
      history.turns.push.apply(history.turns, result.turns || []);
      return true;
    }).catch(function (error) {
      self.histories.delete(id); // reopening allows another load; never overwrite a history we couldn't read
      toast(error.message, true);
      return false;
    });
    return history;
  }
  saveTurns(history) {
    history = history || this.history;
    if (!history) return Promise.resolve();
    var done = history.turns.filter(function (x) { return x.status !== "pending"; }).slice(-MAX_TURNS)
      .map(function (x) { var copy = Object.assign({}, x); delete copy.thumb; return copy; });
    var api = this.app.api, body = { turns: done };
    // Save immediately, in order. Small writes may finish while a window is closing.
    var keepalive = new Blob([JSON.stringify(body)]).size < 60000;
    history.writes = history.writes.then(function () {
      return api.request("PUT", "/api/documents/" + history.id + "/conversation", body, null, keepalive);
    }).catch(function (error) {
      if (error.status !== 404) toast(t("대화 기록을 저장하지 못했어요. 다시 시도해 주세요."), true);
    });
    return history.writes;
  }

  async clearTurns() {
    var history = this.history;
    if (!history || !await history.ready) return;
    history.turns.splice(0);
    await this.saveTurns(history);
    if (this.history !== history || !this.reader) return;
    this.renderThread();
    this.renderHead();
  }

  build() {
    var self = this;
    this.head = h("div", { class: "as-head" });
    this.tabs = h("div", { class: "seg as-tabs" });
    this.body = h("div", { class: "as-body" });
    this.ctx = h("div", { class: "ctx" });
    this.input = h("textarea", { rows: "3", "aria-label": t("이 논문에 대해 물어보세요"), placeholder: t("이 논문에 대해 물어보세요"),
      oninput: function () { self.autosize(); self.sendButton.disabled = !self.input.value.trim(); },
      onkeydown: function (event) {
        if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); self.submit(); }
      } });
    this.sendButton = h("button", { class: "send", title: t("보내기"), disabled: true, onclick: function () { self.submit(); } }, icon("send", 14));
    this.modelSelect = h("select", { "aria-label": t("질문 모델"), onchange: function () {
      var active = self.app.settings.active();
      if (active) self.modelChoices[active.id] = self.modelSelect.value;
    } });
    this.modelRow = h("div", { class: "chat-model" }, this.modelSelect);
    this.composer = h("div", { class: "composer" }, this.ctx, this.input,
      h("div", { class: "row" }, h("span", { class: "hint" }, t("⇧⏎ 줄바꿈")), this.modelRow, this.sendButton));
    this.root.replaceChildren(this.head, this.tabs, this.body, this.composer);
    this.renderHead();
    this.renderContext();
    this.showTab(this.tab, true);
  }

  showTab(tab, quiet) {
    this.tab = tab;
    if (!this.reader) return;
    var self = this;
    if (!quiet) this.app.showAssistant();
    this.tabs.replaceChildren.apply(this.tabs, TABS.map(function (tabItem) {
      return h("button", { class: tabItem[0] === tab ? "on" : "", onclick: function () { self.showTab(tabItem[0]); } }, t(tabItem[1]));
    }));
    this.composer.hidden = tab !== "chat";
    this.renderBody();
  }

  renderBody() {
    if (this.tab === "chat") this.renderThread();
    else if (this.tab === "digest") this.renderDigest();
    else {
      var box = h("div", { class: "thread notes" });
      this.body.replaceChildren(box);
      this.reader.annotations.renderList(box);
    }
  }

  renderHead() {
    var app = this.app, self = this, active = app.settings.active();
    this.renderModelChoice(active);
    this.head.replaceChildren.apply(this.head, [
      h("h2", null, t("AI 도우미")),
      h("button", { class: "provider-pill", title: t("AI 연결 바꾸기"), onclick: function () { app.router.go("/settings"); } },
        h("i", { class: "dot " + (active ? (active.available ? "ok" : "bad") : "") }),
        h("span", null, active ? active.label : t("AI 연결 안 됨"))),
      this.turns.length && this.tab === "chat" ? iconButton("trash", t("대화 지우기"), function () { self.clearTurns(); }) : null,
      iconButton("close", t("패널 닫기 ({key})", { key: MOD + "J" }), function () { app.toggleAssistant(); })].filter(Boolean));
  }

  renderModelChoice(active) {
    var supportsModel = active && active.options.some(function (option) { return option.key === "model"; });
    this.modelRow.hidden = !supportsModel;
    if (!supportsModel) return;
    var self = this, selected = this.modelChoices[active.id] || active.model || "";
    var models = Array.from(new Set([active.model].concat(this.modelCatalogs[active.id] || active.models || [], [selected]).filter(Boolean)));
    this.modelSelect.replaceChildren(h("option", { value: "", selected: !selected },
      active.model ? t("기본 모델 ({model})", { model: active.model }) : t("기본 모델")),
      ...models.map(function (model) { return h("option", { value: model, selected: selected === model }, model); }));
    if (!Object.prototype.hasOwnProperty.call(this.modelCatalogs, active.id)) {
      this.modelCatalogs[active.id] = active.models || [];
      this.app.api.get("/api/providers/" + active.id + "/models").then(function (data) {
        self.modelCatalogs[active.id] = data.models;
        var current = self.app.settings.active();
        if (self.reader && current && current.id === active.id) self.renderModelChoice(current);
      }).catch(function (error) { console.warn(error); });
    }
  }

  renderContext() {
    var self = this;
    if (!this.quoted) { this.ctx.replaceChildren(); this.ctx.style.display = "none"; return; }
    this.ctx.style.display = "";
    this.ctx.replaceChildren(this.quoted.image ? h("img", { class: "ctx-thumb", src: this.quoted.image, alt: "" }) : icon("question", 13),
      h("span", null, "“" + this.quoted.text + "”"),
      iconButton("close", t("인용 빼기"), function () { self.quoted = null; self.renderContext(); }));
  }

  // ---------- conversation ----------
  renderThread() {
    var self = this;
    var quick = h("div", { class: "quick" },
      h("button", { class: "btn small", onclick: function () { self.showTab("digest"); } }, icon("sparkle", 13), t("논문 요약 보기")),
      h("button", { class: "btn small", onclick: function () { self.translatePage(); } }, icon("translate", 13), t("현재 쪽 번역(대화)")));
    if (!this.turns.length) {
      this.body.replaceChildren(h("div", { class: "thread" }, h("div", { class: "as-empty" },
        h("b", null, t("읽다가 막히는 곳을 물어보세요")),
        t("글을 선택해 번역·설명·뜻을 묻거나, 그림·수식 위에 마우스를 올려 설명을 요청하세요. 대화는 논문마다 따로 저장돼요."))), quick);
      return;
    }
    var thread = h("div", { class: "thread" }, this.turns.map(function (turn) { return self.renderTurn(turn); }));
    this.body.replaceChildren(thread, quick);
    thread.scrollTop = thread.scrollHeight;
  }

  renderTurn(turn) {
    var self = this, answer;
    if (turn.status === "pending") {
      answer = h("div", { class: "answer" }, turn.answer || h("span", { class: "typing" }, h("i"), h("i"), h("i")));
      this.pendingAnswers.set(turn, answer);
    } else if (turn.status === "error") {
      answer = h("div", { class: "answer" }, turn.answer || "", h("div", { class: "error-text" }, turn.error),
        turn.code === "provider_unavailable" ? h("div", null, h("button", { class: "btn small", style: "margin-top:6px",
          onclick: function () { self.app.router.go("/settings"); } }, t("설정에서 AI 연결하기"))) : null);
    } else answer = renderMarkdown(h("div", { class: "answer md" }), turn.answer);
    return h("div", { class: "turn" },
      turn.question ? h("div", { class: "ask" }, turn.question) : null,
      h("div", { class: "task" }, turn.label || t(TASK_LABEL[turn.task] || turn.task),
        turn.page ? h("button", { class: "link-btn", onclick: function () { self.reader && self.reader.goToPage(turn.page); } }, "· " + t("{n}쪽", { n: turn.page })) : null),
      turn.thumb ? h("img", { class: "turn-thumb", src: turn.thumb, alt: "" }) : null,
      turn.quote ? h("div", { class: "quote" }, turn.quote) : null,
      answer,
      turn.status === "done" ? h("div", { class: "meta" },
        h("span", null, [turn.provider, turn.model].filter(Boolean).join(" · ") + (turn.cached ? t(" · 저장된 답") : "")),
        h("button", { title: t("복사"), onclick: function () { navigator.clipboard.writeText(turn.answer); toast(t("복사했어요")); } }, icon("copy", 13))) : null);
  }

  autosize() {
    this.input.style.height = "auto";
    this.input.style.height = Math.min(160, this.input.scrollHeight) + "px";
  }

  quote(info) {
    if (!info) return;
    this.showTab("chat");
    this.quoted = info;
    this.renderContext();
    this.input.focus();
  }

  runOnSelection(task, info) {
    if (!info) return;
    this.showTab("chat");
    var context = this.reader.pageText(info.page).slice(0, 6000);
    this.run({ task: task, text: info.text, context: context, quote: info.text, page: info.page });
  }

  runVisual(options) {
    this.showTab("chat");
    this.run({ task: options.task, text: options.text || "", context: options.context || "", images: options.images || [],
      label: t("{name} 설명", { name: options.label }), page: options.page, thumb: options.thumb,
      quote: options.task === "region" && options.text ? options.text.slice(0, 200) : "" });
  }

  submit() {
    var question = this.input.value.trim();
    if (!question || !this.reader) return;
    var quoted = this.quoted;
    this.input.value = "";
    this.autosize();
    this.sendButton.disabled = true;
    this.quoted = null;
    this.renderContext();
    if (quoted && quoted.image) {
      this.run({ task: "region", text: quoted.text, question: question, images: [quoted.image], thumb: quoted.image, page: quoted.page,
        context: this.reader.pageText(quoted.page).slice(0, 4000) });
    } else if (quoted) {
      this.run({ task: "ask", text: quoted.text, question: question, context: this.reader.pageText(quoted.page).slice(0, 6000), quote: quoted.text, page: quoted.page });
    } else {
      var text = this.reader.paperText(50000);
      if (!text) { toast(t("본문을 아직 읽는 중이에요. 잠시 후 다시 물어보세요."), true); return; }
      this.run({ task: "ask", text: text, question: question });
    }
  }

  translatePage() {
    var page = this.reader.current, text = this.reader.pageText(page);
    if (!text) { toast(t("이 쪽에서 글자를 찾지 못했어요."), true); return; }
    this.run({ task: "translate", text: text, page: page, quote: text.slice(0, 160) + (text.length > 160 ? "…" : "") });
  }

  async run(request) {
    var reader = this.reader, history = this.history;
    var active = this.app.settings.active(), model = active ? this.modelChoices[active.id] || "" : "";
    if (!reader || !history || !await history.ready) return;
    var turn = { task: request.task, question: request.question || "", quote: request.quote || "", page: request.page || null,
      label: request.label || "", thumb: request.thumb || null, status: "pending" };
    history.turns.push(turn);
    if (this.reader === reader) {
      if (this.tab === "chat") this.renderThread();
      this.renderHead();
    }
    try {
      var result = await this.app.api.post("/api/assist", {
        task: request.task, text: request.text, question: request.question || "", context: request.context || "",
        title: reader.title(), images: request.images || [], model: model
      }, (delta) => {
        turn.answer = (turn.answer || "") + delta;
        var answer = this.pendingAnswers.get(turn);
        if (!answer || !answer.isConnected) return;
        var thread = answer.closest(".thread");
        var atEnd = thread.scrollHeight - thread.scrollTop - thread.clientHeight < 4;
        if (answer.firstChild?.nodeType === Node.TEXT_NODE) answer.firstChild.appendData(delta);
        else answer.textContent = turn.answer;
        if (atEnd) thread.scrollTop = thread.scrollHeight;
      });
      turn.status = "done";
      turn.answer = result.text;
      turn.provider = this.providerLabel(result.provider_id);
      turn.model = result.model;
      turn.cached = result.cached;
    } catch (error) {
      turn.status = "error";
      turn.error = error.message;
      turn.code = error.code;
    }
    // A response still belongs to its original paper if the user navigated away while waiting.
    await this.saveTurns(history);
    if (!this.reader || this.history !== history) return;
    if (this.tab === "chat") this.renderThread();
  }

  providerLabel(id) {
    var data = this.app.settings.data;
    var found = data && data.providers.find(function (p) { return p.id === id; });
    return found ? found.label : id;
  }

  // ---------- digest: 3-line summary, key terms, full summary ----------
  onAnalysis() {
    this.digest = {};
    this.loadDigest(true);
  }

  digestRequest(task) {
    return { task: task, text: this.reader.paperText(PAPER_LIMIT), title: this.reader.title() };
  }

  async loadDigest(cacheOnly, only) {
    if (!this.reader || !this.reader.analysis || !this.reader.paperText(PAPER_LIMIT).trim()) return;
    var reader = this.reader, self = this;
    var tasks = only ? [only] : ["tldr", "keywords", "summarize"];
    await Promise.all(tasks.map(async function (task) {
      if (!cacheOnly) self.digest[task] = { status: "pending" };
      if (self.tab === "digest") self.renderDigest();
      try {
        var result = await self.app.api.post("/api/assist", Object.assign(self.digestRequest(task), { cache_only: cacheOnly }));
        if (reader !== self.reader) return;
        self.digest[task] = result ? { status: "done", text: result.text, provider: self.providerLabel(result.provider_id), model: result.model } : null;
      } catch (error) {
        if (!cacheOnly) self.digest[task] = { status: "error", text: error.message };
      }
    }));
    if (this.tab === "digest") this.renderDigest();
  }

  keyTerms() {
    var entry = this.digest.keywords;
    if (!entry || entry.status !== "done") return "";
    var terms = this.parseTerms(entry.text);
    return terms ? terms.map(function (x) { return x.term; }).join(", ") : "";
  }

  parseTerms(text) {
    try {
      var start = text.indexOf("{"), end = text.lastIndexOf("}");
      var data = JSON.parse(text.slice(start, end + 1));
      return Array.isArray(data.terms) ? data.terms.filter(function (x) { return x && x.term; }) : null;
    } catch (error) { return null; }
  }

  renderDigest() {
    var self = this, reader = this.reader;
    if (!reader.analysis) {
      this.body.replaceChildren(h("div", { class: "thread" }, h("div", { class: "as-empty" }, t("본문을 읽는 중이에요…"))));
      return;
    }
    function section(task, title, empty, render) {
      var entry = self.digest[task], content;
      if (!entry) content = h("button", { class: "btn small", onclick: function () { self.loadDigest(false, task); } }, icon("sparkle", 13), empty);
      else if (entry.status === "pending") content = h("span", { class: "typing" }, h("i"), h("i"), h("i"));
      else if (entry.status === "error") content = h("div", null, h("div", { class: "error-text" }, entry.text),
        h("button", { class: "btn small", onclick: function () { self.loadDigest(false, task); } }, t("다시 시도")));
      else content = h("div", null, render(entry.text), h("div", { class: "meta" }, [entry.provider, entry.model].filter(Boolean).join(" · ")));
      return h("section", { class: "digest-part" }, h("h3", null, title), content);
    }
    var parts = h("div", { class: "thread digest" },
      section("tldr", t("3줄 요약"), t("3줄 요약 만들기"), function (text) { return renderMarkdown(h("div", { class: "md tldr" }), text); }),
      section("keywords", t("핵심 용어"), t("핵심 용어 정리"), function (text) {
        var terms = self.parseTerms(text);
        if (!terms) return renderMarkdown(h("div", { class: "md" }), text);
        return h("dl", { class: "terms" }, terms.map(function (x) { return [h("dt", null, x.term), h("dd", null, x.meaning || "")]; }));
      }),
      section("summarize", t("전체 요약"), t("전체 요약 만들기"), function (text) { return renderMarkdown(h("div", { class: "md" }), text); }),
      h("p", { class: "fine" }, t("요약은 참고문헌을 뺀 본문으로 만들고, 한 번 만든 결과는 이 컴퓨터에 저장돼 다시 비용이 들지 않아요.")));
    this.body.replaceChildren(parts);
  }
}
