import { h, icon, iconButton, toast, confirmDialog } from "./ui.js";
import { LANGUAGES, t } from "./i18n.js";

var KIND_LABEL = {
  "local-cli": "내 컴퓨터 CLI", "api": "API 키", "local-server": "로컬·자체 서버"
};
var LANGUAGE_NAMES = {
  "Korean": "한국어", "English": "영어", "Japanese": "일본어", "Chinese (Simplified)": "중국어(간체)", "Spanish": "스페인어",
  "French": "프랑스어", "German": "독일어", "Portuguese": "포르투갈어", "Vietnamese": "베트남어"
};
var THEMES = [["system", "시스템 연동"], ["dark", "다크"], ["light", "라이트"]];

export class SettingsView {
  constructor(root, app, route) {
    this.root = root;
    this.app = app;
    this.open = new Set();
    this.results = {};
    this.catalogs = {};
    this.render(true);
  }

  async render(reload) {
    var self = this, app = this.app;
    var toolbar = h("div", { class: "toolbar" },
      app.sidebarHidden() ? iconButton("sidebar", t("사이드바 보이기"), function () { app.toggleSidebar(); }) : null,
      iconButton("back", t("뒤로"), function () { history.length > 1 ? history.back() : app.router.go("/library"); }),
      h("h1", null, t("설정")));
    this.inner = h("div", { class: "settings-inner" });
    this.root.replaceChildren(toolbar, h("div", { class: "settings" }, this.inner));
    if (reload || !app.settings.data) {
      this.inner.append(h("div", { class: "loading" }, t("AI 연결 상태를 확인하는 중…")));
      try { await app.settings.load(); } catch (error) { toast(error.message, true); return; }
    }
    var data = app.settings.data;
    if (!this.open.size && data.provider) this.open.add(data.provider);
    var updates = null;
    try { updates = await app.api.get("/api/updates"); } catch (error) { updates = null; }
    this.inner.replaceChildren(...[
      h("h2", null, t("설정")),
      h("p", { class: "lead" }, t("모든 논문과 설정은 이 컴퓨터에만 저장돼요. API 키는 macOS 키체인에 보관해요.")),
      h("p", { class: "lead" }, t("클라우드 AI를 사용하면 선택한 본문·주변 문맥·그림이 해당 AI 제공자에게 전송돼요. 자동으로 다른 유료 연결로 바꾸지 않아요.")),
      !data.provider || !app.settings.active().available ? h("div", { class: "group" },
        h("p", { class: "desc" }, t("Codex 또는 Claude Code에 로그인한 뒤 다시 확인하세요. 이미 로그인된 연결과 지원 모델을 찾아 선택해요. 유료 응답 시험은 보내지 않아요.")),
        h("button", { class: "btn primary", onclick: async function (event) {
          event.currentTarget.disabled = true;
          try { await app.settings.initialize(); await self.render(false); }
          catch (error) { toast(error.message, true); event.currentTarget.disabled = false; }
        } }, t("로그인 상태 다시 확인"))) : null,
      this.general(data),
      h("h3", null, t("AI 연결")),
      h("p", { class: "lead" }, t("번역·설명·질문에 쓸 AI를 하나 고르세요. 이미 쓰는 계정이나 내 컴퓨터의 모델을 그대로 연결할 수 있어요.")),
      h("div", { class: "group" }, data.providers.map(function (p) { return self.providerCard(p, data.provider); })),
      h("h3", null, t("Claude 데스크톱·Codex에서 내 논문 읽기")),
      this.mcpSection(),
      h("h3", null, t("정보·업데이트")),
      this.updateSection(updates),
      h("h3", null, t("백업·복원")), this.backupSection(),
      h("h3", null, t("지원 범위·개인정보")),
      h("p", { class: "lead" }, t("Mac 베타는 Apple Silicon을 대상으로 해요. 텍스트 PDF 읽기를 지원하며 스캔 문서 OCR과 암호화 PDF는 지원하지 않아요. AI 번역은 원문·수식·인용과 함께 확인해 주세요.")),
      h("a", { class: "btn", href: "/api/diagnostics", download: "PaperDesk-diagnostics.json" }, t("내용 없는 진단 정보 저장"))
    ].filter(Boolean));  // the login-check box is absent once an AI connection works
  }

  updateSection(data) {
    var self = this;
    var automatic = h("input", { type: "checkbox", checked: !!(data && data.automatic_checks),
      disabled: !data || !data.available, "aria-label": t("새 버전 자동 확인"), onchange: async function () {
        automatic.disabled = true;
        try { await self.app.api.put("/api/updates/preferences", { automatic_checks: automatic.checked }); }
        catch (error) { automatic.checked = !automatic.checked; toast(error.message, true); }
        automatic.disabled = false;
      } });
    return h("div", { class: "group", "data-testid": "app-updates" },
      h("div", { class: "field-row" }, h("div", { class: "k" }, t("버전")), h("span", null, data ? data.version : "—")),
      h("div", { class: "field-row" }, h("div", { class: "k" }, t("앱 업데이트"),
        h("small", null, data && data.message ? data.message : t("새 버전 안내에서 다운로드·설치·재실행을 진행해요. 논문과 메모는 유지돼요."))),
        h("button", { class: "btn", disabled: !data || !data.can_check, onclick: async function (event) {
          var button = event.currentTarget;
          button.disabled = true;
          try { await self.app.api.post("/api/updates/check"); await self.render(false); }  // show the new status
          catch (error) { toast(error.message, true); }
          finally { if (button.isConnected) button.disabled = false; }
        } }, t("업데이트 확인"))),
      data && data.restart_ready ? h("div", { class: "field-row" }, h("div", { class: "k" }, t("새 버전 적용"),
        h("small", null, t("앱을 다시 시작하면 받아 둔 새 버전이 적용돼요. 논문과 메모는 그대로예요."))),
        h("button", { class: "btn primary", onclick: async function (event) {
          var button = event.currentTarget;
          button.disabled = true;
          try { await self.app.api.post("/api/updates/restart"); toast(t("다시 시작하는 중…")); }  // the window closes and reopens
          catch (error) { toast(error.message, true); button.disabled = false; }
        } }, t("지금 다시 시작"))) : null,
      h("div", { class: "field-row" }, h("div", { class: "k" }, t("새 버전 자동 확인"),
        h("small", null, t("켜면 주기적으로 업데이트 서버에 연결해 새 버전을 확인해요."))), automatic));
  }

  general(data) {
    var app = this.app, self = this;
    var choice = window.paperdeskTheme.get();
    var seg = h("div", { class: "seg", role: "radiogroup" }, THEMES.map(function (item) {
      return h("button", { class: choice === item[0] ? "on" : "", role: "radio", "aria-checked": String(choice === item[0]),
        onclick: function () { window.paperdeskTheme.set(item[0]); app.themeChanged(); self.render(false); } }, t(item[1]));
    }));
    var languages = data.languages.indexOf(data.target_language) >= 0 ? data.languages : [data.target_language].concat(data.languages);
    var select = h("select", { onchange: async function () {
      try { await app.api.put("/api/settings", { target_language: select.value }); await app.settings.load(); toast(t("번역 언어를 바꿨어요")); }
      catch (error) { toast(error.message, true); }
    } }, languages.map(function (lang) { return h("option", { value: lang, selected: lang === data.target_language }, t(LANGUAGE_NAMES[lang] || lang)); }));
    var uiSelect = h("select", { "aria-label": t("화면 언어"), onchange: async function () {
      try {
        await app.api.put("/api/settings", { ui_language: uiSelect.value });
        await app.applyLanguage(uiSelect.value);
      } catch (error) { toast(error.message, true); }
    } }, [["system", t("시스템 연동")]].concat(LANGUAGES).map(function (item) {
      return h("option", { value: item[0], selected: item[0] === (data.ui_language || "system") }, item[1]);
    }));
    function toggle(key, label, help) {
      var box = h("input", { type: "checkbox", checked: !!data[key], "aria-label": label, onchange: async function () {
        box.disabled = true;
        try { app.settings.data = await app.api.put("/api/settings", { [key]: box.checked }); }
        catch (error) { box.checked = !box.checked; toast(error.message, true); }
        finally { box.disabled = false; }
      } });
      return h("div", { class: "field-row" }, h("div", { class: "k" }, label, h("small", null, help)), box);
    }
    return h("div", { class: "group" },
      toggle("auto_translate", t("논문 열 때 본문 자동 번역"),
        t("켜면 미번역 본문 전체를 연결한 AI로 번역해요. 사용량이나 요금이 발생할 수 있어요. 저장된 번역은 재사용하고 멈춘 작업은 자동 재개하지 않아요.")),
      toggle("auto_info", t("논문 정보 자동으로 찾기"),
        t("추가한 논문의 저자·연도·학회·DOI를 arXiv와 OpenAlex에서 찾아요. 이때 논문 제목과 첫 쪽의 arXiv 번호·DOI가 이 두 서비스로 보내져요.")),
      toggle("auto_organize", t("폴더 없이 추가한 논문 자동 정리"),
        t("연결한 AI가 내 폴더 중에서 알맞은 곳을 고르고, 맞는 폴더가 없으면 새로 만들어요. 한 편에 사용량이 조금 발생해요. 폴더를 골라 가져온 논문은 그대로 둬요.")),
      h("div", { class: "field-row" }, h("div", { class: "k" }, t("화면 언어"), h("small", null, t("메뉴와 버튼에 쓰는 언어예요. 처음에는 시스템 언어를 따라요."))), uiSelect),
      h("div", { class: "field-row" }, h("div", { class: "k" }, t("화면 테마"), h("small", null, t("PDF 지면은 어느 테마에서나 흰색으로 보여요."))), seg),
      h("div", { class: "field-row" }, h("div", { class: "k" }, t("번역·답변 언어"), h("small", null, t("처음에는 시스템 언어를 따라요."))), select));
  }

  providerCard(p, activeId) {
    var self = this, app = this.app;
    var isOpen = this.open.has(p.id);
    if (this.catalogs[p.id]) p.models = this.catalogs[p.id];
    var radio = h("input", { type: "radio", name: "provider", checked: p.id === activeId, "aria-label": t("{name} 사용", { name: p.label }),
      onclick: function (event) { event.stopPropagation(); self.activate(p.id); } });
    var head = h("div", { class: "provider-head", onclick: function () {
      if (self.open.has(p.id)) self.open.delete(p.id); else self.open.add(p.id);
      self.render(false);
    } },
      radio, h("span", { class: "name" }, p.label), h("span", { class: "kind" }, t(KIND_LABEL[p.kind] || p.kind)),
      h("span", { class: "state" }, h("i", { class: "dot " + (p.available ? "ok" : "bad") }), h("span", { title: p.detail }, p.available ? (p.kind === "local-cli" ? t("로그인 확인됨 · 응답 시험 필요") : t("사용 가능")) : t("설정 필요"))));
    var inputs = {};
    var grid = h("div", { class: "form-grid" });
    p.options.forEach(function (option) {
      var id = "opt-" + p.id + "-" + option.key, input;
      if (option.kind === "secret") {
        input = h("input", { id: id, class: "text", type: "password", autocomplete: "off",
          placeholder: option.from_env ? t("{name} 환경 변수 사용 중", { name: option.env }) : option.has_value ? t("저장됨 · 바꾸려면 새로 입력") : (option.placeholder || "") });
      } else {
        var listId = option.key === "model" && p.models.length ? id + "-list" : null;
        input = h("input", { id: id, class: "text", value: option.value || "", placeholder: option.default || option.placeholder || "",
          list: listId, spellcheck: "false" });
        if (listId) grid.append(h("datalist", { id: listId }, p.models.map(function (m) { return h("option", { value: m }); })));
      }
      inputs[option.key] = { input: input, option: option };
      grid.append(h("label", { for: id }, option.label), input);
      if (option.help) grid.append(h("div", { class: "help" }, option.help));
      if (option.key === "model" && p.models.length) grid.append(h("div", { class: "help" }, t("서버의 모델: {list}", { list: p.models.slice(0, 8).join(", ") })));
    });
    var result = this.results[p.id];
    var body = h("div", { class: "provider-body" },
      h("p", { class: "desc" }, p.description, p.docs_url ? [" ", h("a", { href: p.docs_url, target: "_blank", rel: "noreferrer" }, t("안내 문서"))] : null),
      h("p", { class: "desc", style: "font-size:12px" }, t("상태: {detail}", { detail: p.detail })),
      p.kind === "local-cli" ? h("p", { class: "desc" }, p.id === "codex-cli" ? t("CLI를 설치한 뒤 터미널에서 codex login을 실행하세요. 설치·모델 확인 후 모델을 저장하고 연결 시험을 해 주세요.") : t("Claude Code를 설치한 뒤 터미널에서 claude를 실행해 /login 하세요. 연결 시험에는 소량의 사용량이 발생해요.")) : null,
      p.supports_images ? null : h("p", { class: "desc", style: "font-size:12px" }, t("그림·수식 설명은 이미지 없이 캡션과 본문 글자만 보내 설명해요.")),
      p.options.length ? grid : null,
      h("div", { class: "actions-row" },
        p.kind === "local-cli" ? h("button", { class: "btn", onclick: function (event) { self.discover(p, event.currentTarget); } }, t("설치·모델 확인")) : null,
        p.options.length ? h("button", { class: "btn", onclick: function () { self.save(p, inputs); } }, t("저장")) : null,
        h("button", { class: "btn", onclick: function (event) { self.test(p, event.currentTarget); } }, t("연결 시험")),
        p.id !== activeId ? h("button", { class: "btn primary", onclick: function () { self.activate(p.id); } }, t("이 AI 사용")) : null,
        p.options.some(function (o) { return o.kind === "secret" && o.has_value && !o.from_env; }) ?
          h("button", { class: "btn danger", onclick: function () { self.clearSecrets(p); } }, t("저장된 키 삭제")) : null,
        result ? h("span", { class: "result " + (result.ok ? "ok" : "bad") }, result.text) : null));
    return h("div", { class: "provider" + (isOpen ? " open" : "") }, head, body);
  }

  async activate(id) {
    try {
      var tested = await this.app.api.post("/api/providers/" + id + "/test");
      if (!tested.ok) { toast(tested.message, true); return; }
      await this.app.api.put("/api/settings", { provider: id });
      this.open.add(id);
      await this.app.settings.load();
      toast(t("사용할 AI를 바꿨어요"));
      this.render(false);
    } catch (error) { toast(error.message, true); }
  }

  async discover(p, button) {
    button.disabled = true;
    try {
      var result = await this.app.api.post("/api/providers/" + p.id + "/discover");
      this.catalogs[p.id] = result.models || [];
      this.results[p.id] = { ok: !!result.selected, text: result.candidates.map(function (c) { return c.version + " · " + c.path; }).join(" / ") || t("CLI를 찾지 못했어요. 설치 후 다시 확인해 주세요.") };
      await this.app.settings.load();
      this.render(false);
    } catch (error) { toast(error.message, true); button.disabled = false; }
  }

  backupSection() {
    var self = this;
    var input = h("input", { type: "file", accept: ".paperdesk,.zip", hidden: true, onchange: function () {
      if (input.files.length) self.inspectBackup(input.files[0]);
    } });
    return h("div", { class: "group" }, h("div", { class: "field-row", style: "display:block" },
      h("p", { class: "desc" }, t("백업에는 PDF·번역·메모·대화·설정이 포함돼요. API 키와 로그인 정보는 제외돼요. 암호화되지 않은 파일이므로 안전한 곳에 보관하세요.")),
      h("button", { class: "btn", onclick: async function (event) {
        var button = event.currentTarget; button.disabled = true;
        try {
          var result = await self.app.api.post("/api/backups/export");
          var link = h("a", { href: result.url, download: "PaperDesk-backup.paperdesk" });
          document.body.append(link); link.click(); link.remove();
        } catch (error) { toast(error.message, true); }
        finally { button.disabled = false; }
      } }, t("전체 백업 저장")), " ",
      h("button", { class: "btn", onclick: function () { input.click(); } }, t("백업 확인·복원")), input));
  }

  async inspectBackup(file) {
    if (file.size > 200*1024*1024) { toast(t("화면에서 복원할 백업은 200MB까지 지원해요. 큰 백업은 CLI로 복원해 주세요."), true); return; }
    try {
      var data = await this.app.api.request("POST", "/api/backups/inspect", file, { "Content-Type": "application/zip" });
      var ok = await confirmDialog({ title: t("서재를 복원할까요?"), confirm: t("다음 실행에 복원"),
        message: t("논문 {n}편의 백업을 확인했어요. 앱을 완전히 종료하고 다시 열면 현재 서재를 교체해요. 이전 서재는 복구용 폴더에 보존해요. 복원 전까지 추가한 작업은 새 서재에 포함되지 않아요. AI 연결은 다시 확인해 주세요.", { n: data.documents }) });
      if (!ok) return;
      await this.app.api.post("/api/backups/restore", { token: data.token });
      toast(t("복원을 예약했어요. 앱을 완전히 종료한 뒤 다시 열어 주세요."));
    } catch (error) { toast(error.message, true); }
  }

  async save(p, inputs) {
    var values = {};
    Object.keys(inputs).forEach(function (key) {
      var entry = inputs[key], value = entry.input.value.trim();
      if (entry.option.kind === "secret") { if (value) values[key] = value; }
      else values[key] = value;
    });
    try {
      await this.app.api.put("/api/providers/" + p.id, { values: values });
      await this.app.settings.load();
      toast(t("저장했어요"));
      this.render(false);
    } catch (error) { toast(error.message, true); }
  }

  async clearSecrets(p) {
    var values = {};
    p.options.forEach(function (o) { if (o.kind === "secret") values[o.key] = null; });
    try {
      await this.app.api.put("/api/providers/" + p.id, { values: values });
      await this.app.settings.load();
      this.render(false);
    } catch (error) { toast(error.message, true); }
  }

  async test(p, button) {
    button.disabled = true;
    button.textContent = t("시험 중…");
    try {
      var result = await this.app.api.post("/api/providers/" + p.id + "/test");
      this.results[p.id] = { ok: result.ok, text: result.ok ? t("응답 받음 ({seconds}초{model})", { seconds: result.seconds, model: result.model ? ", " + result.model : "" }) : result.message };
    } catch (error) {
      this.results[p.id] = { ok: false, text: error.message };
    }
    this.render(false);
  }

  mcpSection() {
    return h("div", { class: "group" }, h("div", { class: "field-row", style: "display:block" },
      h("p", { class: "desc", style: "margin:0 0 6px;color:var(--text-2)" },
        t("Claude 데스크톱이나 Codex 앱이 PaperDesk에 저장된 논문 목록·본문·검색 결과를 읽을 수 있게 연결해요. "),
        t("이 방식은 각 앱이 공식 지원하는 MCP를 쓰고, 그 앱의 로그인 정보에는 접근하지 않아요. 터미널에서 아래 명령을 실행해 나온 내용을 각 앱 설정에 붙여 넣으세요.")),
      h("pre", { class: "code" }, t("paperdesk mcp-config claude   # Claude 데스크톱\npaperdesk mcp-config codex    # Codex"))));
  }
}
