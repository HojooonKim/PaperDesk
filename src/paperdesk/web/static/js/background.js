// After an import, prepare each paper in the background so it is ready when opened: its text, its details (authors,
// year, venue, DOI), a folder when it was added without one, and with automatic translation on, its translation.
// These are the reader's steps without a reader: text from pdf.js, the Docling analysis, then one translation job.
import { loadPdfjs, readPages } from "./pdf.js";
import { analyzeDocling } from "./layout.js";
import { toast } from "./ui.js";
import { t } from "./i18n.js";

var POLL = 2000, ANALYSIS_LIMIT = 15 * 60 * 1000;
var LOOKUP_GAP = 3000;  // between papers when filling in older ones: arXiv asks for one request every three seconds

function wait(ms) { return new Promise(function (resolve) { setTimeout(resolve, ms); }); }
function warn(label, id) { return function (error) { console.warn(label, id, error); }; }

// The message after a paper was sorted into a folder (result: the organize reply, which has a folder).
export function placed(result) {
  var names = { title: result.document.title, folder: result.folder.name };
  return result.created ? t("새 폴더 '{folder}'을(를) 만들어 '{title}'을(를) 넣었어요", names) : t("'{title}'을(를) '{folder}' 폴더에 넣었어요", names);
}

export class BackgroundImport {
  constructor(app) {
    this.app = app;
    this.queue = Promise.resolve();         // text, details and folder: one paper at a time
    this.translations = Promise.resolve();  // the analysis can take minutes, so translations wait in their own line
  }

  // organize: the papers were added without choosing a folder, so they may be sorted into one.
  add(ids, organize) {
    var self = this;
    ids.forEach(function (id) {
      self.queue = self.queue.then(function () { return self.prepare(id, organize); }).then(function (pages) {
        if (pages) self.translations = self.translations.then(function () { return self.translate(id, pages); }).catch(warn("background translation", id));
      }).catch(warn("background import", id));
    });
  }

  // Papers added before details were looked up (or while offline) get them too, slowly.
  fillDetails(docs) {
    var self = this, settings = this.app.settings.data;
    if (!settings || !settings.auto_info) return;
    docs.filter(function (doc) { return !doc.info_checked_at; }).forEach(function (doc) {
      self.queue = self.queue.then(async function () {
        await self.details(doc.id);
        await wait(LOOKUP_GAP);
      }).catch(warn("paper details", doc.id));
    });
  }

  ready() {
    var provider = this.app.settings.active();
    return !!(provider && provider.available);
  }

  async prepare(id, organize) {
    var settings = this.app.settings.data || {};
    var pages = await this.readText(id);
    if (!pages) return null;
    var doc = (await this.app.api.get("/api/documents/" + id)).document;
    if (settings.auto_info) doc = (await this.details(id)) || doc;
    if (organize && settings.auto_organize && !doc.folder_id && this.ready()) {
      try { var result = await this.organize(id); if (result.folder) toast(placed(result)); }
      catch (error) { toast(t("자동 정리하지 못했어요: {message}", { message: error.message }), true); }
    }
    return settings.auto_translate && this.ready() ? pages : null;
  }

  // Text of every page, saved for search, details and sorting; null for papers the reader refuses (over 500 pages).
  async readText(id) {
    var api = this.app.api, lib = await loadPdfjs();
    var pdf = await lib.getDocument({ url: "/api/documents/" + id + "/file", isEvalSupported: false }).promise;
    var pages;
    try {
      if (pdf.numPages > 500) return null;
      pages = await readPages(pdf);
    } finally {
      pdf.destroy();
    }
    var doc = (await api.get("/api/documents/" + id)).document;
    if (doc.text_pages !== pages.texts.length) await api.put("/api/documents/" + id + "/text", { pages: pages.texts });
    return pages;
  }

  async details(id) {
    try {
      var doc = (await this.app.api.post("/api/documents/" + id + "/info", {})).document;
      await this.app.store.load();
      return doc;
    } catch (error) {
      console.warn("paper details", id, error);
      return null;
    }
  }

  async organize(id) {
    var result = await this.app.api.post("/api/documents/" + id + "/organize", {});
    await this.app.store.load();
    return result;
  }

  async translate(id, pages) {
    var api = this.app.api;
    var layout = await this.analysis(id);
    if (!layout) return;
    var doc = (await api.get("/api/documents/" + id)).document;
    var blocks = analyzeDocling(pages.layout, layout).blocks.filter(function (b) { return b.translatable; });
    var saved = await api.get("/api/documents/" + id + "/translations");
    var jobs = (await api.get("/api/documents/" + id + "/translation-jobs")).jobs;
    // Opened meanwhile, the reader may have started one already (and the server never queues a paragraph twice).
    if (jobs.some(function (job) { return job.language === saved.language && job.state !== "completed"; })) return;
    var fresh = blocks.filter(function (b) { return !saved.blocks[b.key]; });
    if (fresh.length) await api.post("/api/documents/" + id + "/translation-jobs", {
      blocks: fresh.map(function (b) { return { key: b.key, sentences: b.sentences }; }), title: doc.title, terms: "" });
  }

  async analysis(id) {
    var api = this.app.api, data = await api.post("/api/documents/" + id + "/analysis", { retry: false });
    for (var end = Date.now() + ANALYSIS_LIMIT; data.state !== "completed" && data.state !== "failed" && Date.now() < end;) {
      await wait(POLL);
      data = await api.get("/api/documents/" + id + "/analysis");
    }
    return data.state === "completed" ? data.layout : null;
  }
}
