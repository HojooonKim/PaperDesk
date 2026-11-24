// Document analysis from pdf.js text positions: lines -> blocks -> kinds (paragraph, heading, caption, equation, ...),
// figure/table/algorithm regions, equations and sections. Pure functions; coordinates are PDF points from the page's
// top-left, rects exported to the UI are page fractions [left, top, right, bottom].

var CAPTION = /^(Figure|Fig\.?|Table|Tab\.?|Algorithm|Alg\.?)\s*(\d+|[A-Z]\.?\d+|[IVX]+)(?:\s*[:.|—–]\s*|\s+(?=[A-Z]))/;
var NAMED_HEADING = /^(abstract|introduction|related work|background|preliminar(y|ies)|method(s|ology)?|approach|experiments?|results|evaluation|discussion|conclusions?|limitations?|future work|acknowledge?ments?|references|bibliography|appendix|appendices|broader impacts?|ethics statement|reproducibility statement)\b/i;
var NUMBERED_HEADING = /^((\d{1,2}(\.\d{1,2}){0,3})|([A-H](\.\d{1,2}){0,3}))\.?\s+(\S.*)$/;
var REFERENCES = /^(?:\d+\.?\s*)?(references|bibliography|literature cited|works cited|참고\s*문헌)\s*$/i;
var MATH_CHARS = /[=+\u2212×·∑∏∫∂∇√∞≤≥≈≠∈∉⊂⊆∪∩→←↦⇒⇔∀∃αβγδεζηθικλμνξπρστυφχψωΓΔΘΛΞΠΣΦΨΩ^_{}|‖⟨⟩]/g;
var EQ_NUMBER = /\(\s*(\d{1,3}[a-z]?|[A-Z]\.\d{1,3})\s*\)\s*$/;

export function hashText(text) {
  // cyrb53: short, stable key for a block's text
  var h1 = 0xdeadbeef, h2 = 0x41c6ce57;
  for (var i = 0; i < text.length; i++) {
    var ch = text.charCodeAt(i);
    h1 = Math.imul(h1 ^ ch, 2654435761);
    h2 = Math.imul(h2 ^ ch, 1597334677);
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  return (4294967296 * (2097151 & h2) + (h1 >>> 0)).toString(36);
}

export function compact(text) { return String(text || "").replace(/[\s\u00ad]+/g, ""); }

var ABBREV = /(?:\b(?:e\.g|i\.e|et al|etc|vs|cf|resp|approx|Fig|Figs|Eq|Eqs|Sec|Secs|Tab|Alg|No|Nos|Ref|Refs|Dr|Mr|Ms|Prof|St|Jr|Sr|Inc|Ltd|Co|Corp|Vol|pp|Ch|App|Thm|Lem|Def|Prop|Cor)|\b[A-Z]|\d)\.$/;

export function splitSentences(text) {
  var out = [];
  // bullet lists: every "•" item is its own sentence group
  String(text || "").split(/\s+(?=[•▪◦]\s)/).forEach(function (item) { out.push.apply(out, splitPlain(item)); });
  return out;
}

function splitPlain(text) {
  var parts = String(text || "").split(/(?<=[.!?]["”’)\]]?)\s+(?=["“(\[]?[A-Z0-9])/);
  var out = [];
  parts.forEach(function (part) {
    if (out.length && (ABBREV.test(out[out.length - 1]) || out[out.length - 1].length < 12)) out[out.length - 1] += " " + part;
    else out.push(part);
  });
  return out.map(function (s) { return s.trim(); }).filter(Boolean);
}

function median(values) {
  var s = values.filter(function (v) { return v > 0; }).sort(function (a, b) { return a - b; });
  return s.length ? s[Math.floor(s.length / 2)] : 10;
}
function mathRatio(text) {
  var plain = text.replace(/\s+/g, "");
  if (!plain) return 0;
  var symbols = (plain.match(MATH_CHARS) || []).length;
  var words = (text.match(/\b[a-z]{4,}\b/g) || []).length;
  return symbols / plain.length + (words <= 1 ? 0.1 : 0) - words * 0.03;
}

// A gutter is a vertical gap supported by many rows, not an unusually wide word space.
function columnGutter(rows, width) {
  var votes = new Map();
  rows.forEach(function (row) {
    var runs = row.runs.slice().sort(function (a, b) { return a.x0 - b.x0; });
    var left = Math.min.apply(null, runs.map(function (r) { return r.x0; }));
    var right = Math.max.apply(null, runs.map(function (r) { return r.x1; })), end = left;
    runs.forEach(function (run) {
      for (var x = Math.ceil(Math.max(end + 1, width * 0.3)); x < Math.min(run.x0 - 1, width * 0.7); x++) {
        if (x - left > width * 0.2 && right - x > width * 0.2) votes.set(x, (votes.get(x) || 0) + 1);
      }
      end = Math.max(end, run.x1);
    });
  });
  var best = Math.max(0, ...votes.values());
  if (best < Math.max(6, rows.length * 0.2)) return null;
  var positions = Array.from(votes.keys()).filter(function (x) { return votes.get(x) === best; }).sort(function (a, b) { return a - b; });
  return positions[Math.floor(positions.length / 2)];
}

function baselineRows(runs) {
  var rows = [];
  runs.slice().sort(function (a, b) { return a.base - b.base || a.x0 - b.x0; }).forEach(function (run) {
    var row = rows[rows.length - 1];
    if (row && Math.abs(run.base - row.base) < Math.max(2, Math.min(row.size, run.size) * 0.45)) {
      row.runs.push(run);
      if (run.size > row.size) { row.size = run.size; row.base = run.base; }
    } else rows.push({ base: run.base, size: run.size, runs: [run] });
  });
  return rows;
}

// ---- 1. glyph runs -> lines ----
function pageLines(page) {
  var view = page.view || [0, 0, page.width, page.height];
  var runs = [];
  page.items.forEach(function (item) {
    if (typeof item.str !== "string" || !item.str.trim()) return;
    var t = item.transform, size = item.height || Math.hypot(t[2], t[3]) || 1;
    if (Math.abs(t[1]) > Math.abs(t[0]) * 0.5) return; // rotated text (watermarks, arXiv side stamp)
    var x0 = t[4] - view[0], base = view[3] - t[5];
    var font = page.styles && page.styles[item.fontName];
    runs.push({ str: item.str, font: item.fontName, x0: x0, x1: x0 + Math.max(item.width || 0, size * 0.3), base: base, size: size,
      top: base - size * Math.max(0.82, font ? font.ascent : 0), bottom: base + size * Math.max(0.22, font ? -font.descent : 0) });
  });
  var rough = baselineRows(runs), gutter = columnGutter(rough, page.width), groups = {};
  rough.forEach(function (row) {
    var full = gutter !== null && row.runs.some(function (r) { return r.x0 < gutter && r.x1 > gutter; });
    row.runs.forEach(function (run) {
      var col = gutter === null ? "S" : full ? "F" : run.x1 <= gutter ? "L" : "R";
      (groups[col] || (groups[col] = [])).push(run);
    });
  });
  var rows = [];
  Object.keys(groups).forEach(function (col) {
    baselineRows(groups[col]).forEach(function (row) { row.col = col; rows.push(row); });
  });
  // Sub/superscripts sit on their own baseline; fold small, short rows into the neighbouring text row
  // so "v" + "θ" or "word" + "2" stay on one line instead of splitting paragraphs.
  var normal = median(rows.map(function (r) { return r.size; }));
  rows = rows.filter(function (row, index) {
    var text = row.runs.map(function (r) { return r.str; }).join("").replace(/\s+/g, "");
    if (row.size >= normal * 0.8 || text.length > 8) return true;
    var x0 = Math.min.apply(null, row.runs.map(function (r) { return r.x0; })), x1 = Math.max.apply(null, row.runs.map(function (r) { return r.x1; }));
    var best = null, distance = Infinity;
    [rows[index - 1], rows[index + 1]].forEach(function (other) {
      if (!other || other.col !== row.col || other.size < normal * 0.8) return;
      var ox0 = Math.min.apply(null, other.runs.map(function (r) { return r.x0; })), ox1 = Math.max.apply(null, other.runs.map(function (r) { return r.x1; }));
      var d = Math.abs(other.base - row.base);
      if (d < other.size * 0.95 && x1 > ox0 - other.size && x0 < ox1 + other.size && d < distance) { best = other; distance = d; }
    });
    if (!best) return true;
    best.runs = best.runs.concat(row.runs);
    return false;
  });
  var lines = [];
  rows.forEach(function (row) {
    row.runs.sort(function (a, b) { return a.x0 - b.x0; });
    var segment = null, segments = [];
    row.runs.forEach(function (run) {
      var gap = segment ? run.x0 - segment.x1 : 0;
      if (!segment || gap > Math.max(row.size * 2.5, 7)) {
        segment = { runs: [run], x0: run.x0, x1: run.x1 };
        segments.push(segment);
      } else {
        segment.runs.push(run);
        segment.x1 = Math.max(segment.x1, run.x1);
      }
    });
    // an equation number set far to the right belongs to the formula on its row
    for (var k = segments.length - 1; k > 0; k--) {
      var only = segments[k].runs.map(function (r) { return r.str; }).join("").trim();
      if (/^\(\s*(\d{1,3}[a-z]?|[A-Z]\.\d{1,3})\s*\)$/.test(only)) {
        segments[k - 1].runs = segments[k - 1].runs.concat(segments[k].runs);
        segments[k - 1].x1 = segments[k].x1;
        segments.splice(k, 1);
      }
    }
    segments.forEach(function (seg) {
      var text = "", previous = null, sizes = [];
      seg.runs.forEach(function (run) {
        if (previous && run.x0 - previous.x1 > row.size * 0.15 && !/\s$/.test(text) && !/^\s/.test(run.str)) text += " ";
        text += run.str;
        sizes.push(run.size);
        previous = run;
      });
      lines.push({ page: page.number, col: row.col, x0: seg.x0, x1: seg.x1, base: row.base,
        top: Math.min.apply(null, seg.runs.map(function (r) { return r.top; })),
        bottom: Math.max.apply(null, seg.runs.map(function (r) { return r.bottom; })),
        size: median(sizes), text: text.replace(/\s+/g, " ").trim(), runs: seg.runs, siblings: segments.length - 1 });
    });
  });
  return lines.filter(function (l) { return l.text; });
}

// ---- 2. columns and reading order ----
function orderLines(lines, width) {
  var left = lines.filter(function (l) { return l.col === "L"; }).length;
  var right = lines.filter(function (l) { return l.col === "R"; }).length;
  var twoColumn = left >= 6 && right >= 6;
  if (!twoColumn) {
    lines.forEach(function (l) { l.col = "S"; });
    return { lines: lines.slice().sort(function (a, b) { return a.top - b.top || a.x0 - b.x0; }), twoColumn: false };
  }
  var sorted = lines.slice().sort(function (a, b) { return a.top - b.top || a.x0 - b.x0; }), out = [], band = [];
  function flush() {
    ["L", "R"].forEach(function (col) { band.filter(function (l) { return l.col === col; }).forEach(function (l) { out.push(l); }); });
    band = [];
  }
  sorted.forEach(function (l) { if (l.col === "F") { flush(); out.push(l); } else band.push(l); });
  flush();
  return { lines: out, twoColumn: true };
}

function columnBounds(lines, col, width) {
  var own = lines.filter(function (l) { return l.col === col; });
  if (!own.length) return col === "R" ? [width / 2, width] : [0, width / 2];
  var xs = own.map(function (l) { return l.x0; }), xe = own.map(function (l) { return l.x1; });
  return [median(xs) - 2, Math.max.apply(null, xe)];
}

// ---- 3. line kinds that force their own block ----
function headingLike(line, ctx) {
  var t = line.text, m = NUMBERED_HEADING.exec(t);
  if (!m || t.length > 90 || /[.,;:]["”’']?$/.test(t) || /["“”]/.test(m[6]) || !/^[A-Z]/.test(m[6]) || !/[A-Za-z]{3,}/.test(m[6])) return false;
  if (/^\d+(\.\d+)?\s+[\d.%±]+/.test(t) || m[6].split(/\s+/).length > 12) return false;
  if (ctx.repeated.has(t.replace(/\d+/g, "#"))) return false;  // running header such as "A Kinetic Energy ..."
  if (/^[A-H]\s/.test(t) && line.size < ctx.body * 1.04) return false;  // "A Study of ..." sentence, not appendix A
  var bounds = ctx.bounds[line.col];
  return line.size >= ctx.body * 1.04 || line.x1 < bounds[0] + (bounds[1] - bounds[0]) * 0.7;
}

function lineKind(line, ctx) {
  var t = line.text;
  if (CAPTION.test(t)) return "caption";
  if (headingLike(line, ctx)) return "heading";
  var ratio = mathRatio(t);
  var bounds = ctx.bounds[line.col], colWidth = bounds[1] - bounds[0];
  var centered = Math.abs((line.x0 + line.x1) / 2 - (bounds[0] + bounds[1]) / 2) < colWidth * 0.12 && (line.x1 - line.x0) < colWidth * 0.8;
  if (EQ_NUMBER.test(t) && (ratio > 0.08 || centered) && t.length < 220) return "math";
  if (centered && ratio > 0.18 && t.length < 160) return "math";
  if (/^\d{1,2}\s*:\s/.test(t) && line.size <= ctx.body * 1.02) return "algo";
  if (line.siblings >= 2 && t.length < 40) return "cell";
  return "text";
}

// ---- 4. blocks ----
function makeBlocks(lines, ctx) {
  var blocks = [], current = null;
  function shouldBreak(prev, line) {
    if (!current || line.col !== prev.col || line.top < prev.top - 2) return true;
    if (line.kind === "caption" || line.kind === "heading") return true;
    if (current.lineKind === "heading") {
      // a long heading wraps onto a second, unnumbered line of the same size
      return !(line.size >= ctx.body * 1.04 && Math.abs(line.size - prev.size) < 0.6 && line.top - prev.bottom < line.size * 0.6 && current.lines.length < 3);
    }
    var gap = line.top - prev.bottom, size = Math.max(line.size, prev.size);
    if (current.lineKind === "math" && line.kind === "math") return gap > size * 1.6;
    var continuesCaption = current.lineKind === "caption";
    if (line.kind !== current.lineKind && !continuesCaption) return true;
    if (gap > size * 0.65) return true;
    if (Math.abs(line.size - prev.size) > size * 0.14) return true;
    if (continuesCaption) return false;
    var bounds = ctx.bounds[line.col], colWidth = bounds[1] - bounds[0];
    var first = line.runs[0];
    // Run-in labels and unindented paragraphs need their own blocks too.
    var runIn = first.font && first.font !== ctx.bodyFont && /^[A-Z][A-Za-z -]{2,55}[.:]$/.test(first.str.trim());
    return line.kind === "text" && (runIn || (prev.x1 < bounds[0] + colWidth * 0.9 && /[.!?:]$/.test(prev.text)));
  }
  lines.forEach(function (line) {
    line.kind = lineKind(line, ctx);
    var prev = current && current.lines[current.lines.length - 1];
    var start = shouldBreak(prev, line);
    if (start) {
      current = { lines: [line], lineKind: line.kind === "caption" ? "caption" : line.kind, col: line.col, page: line.page };
      blocks.push(current);
    } else current.lines.push(line);
  });
  blocks.forEach(function (b, index) {
    b.index = index;
    b.x0 = Math.min.apply(null, b.lines.map(function (l) { return l.x0; }));
    b.x1 = Math.max.apply(null, b.lines.map(function (l) { return l.x1; }));
    b.top = Math.min.apply(null, b.lines.map(function (l) { return l.top; }));
    b.bottom = Math.max.apply(null, b.lines.map(function (l) { return l.bottom; }));
    b.size = median(b.lines.map(function (l) { return l.size; }));
    var text = "";
    b.lines.forEach(function (l) {
      if (!text) text = l.text;
      else if (/[A-Za-z]-$/.test(text)) text += l.text; // keep the hyphen: matches the PDF text layer
      else text += " " + l.text;
    });
    b.text = text;
  });
  return blocks;
}

// ---- 5. block kinds ----
function classify(block, ctx) {
  var t = block.text, words = t.split(/\s+/).length, page = ctx.page;
  if (block.lines.length <= 2 && ctx.repeated.has(t.replace(/\d+/g, "#"))) return "furniture";
  if (block.lineKind === "math") return "equation";
  if (block.lineKind === "algo") return "algorithm";
  if (block.lineKind === "cell") return "table";
  if (block.lineKind === "caption") return "caption";
  if (block.lineKind === "heading") return "heading";
  var edge = block.bottom < page.height * 0.075 || block.top > page.height * 0.93;
  if (edge && block.lines.length <= 2) return /^\d{1,4}$/.test(t) || ctx.repeated.has(t.replace(/\d+/g, "#")) || words <= 14 ? "furniture" : "paragraph";
  if (/^\d{1,4}$/.test(t)) return "furniture";
  if (block.lines.length <= 2 && t.length <= 110 && !/[.,;:?]["”’']?$/.test(t.replace(/\s*\d+$/, ""))) {
    var numbered = NUMBERED_HEADING.exec(t);
    var big = block.size >= ctx.body * 1.08;
    if (numbered && /^[A-Z]/.test(numbered[6]) && words <= 14 && !/^\d+(\.\d+)?\s+[\d.%]+/.test(t) && (big || words <= 10)) return "heading";
    if (NAMED_HEADING.test(t) && words <= 6) return "heading";
    if (big && words >= 2 && words <= 14 && block.size >= ctx.body * 1.15 && /^[A-Z]/.test(t) && /[a-z]{3}/.test(t)) return "heading";
  }
  if (block.size < ctx.body * 0.93 && block.top > page.height * 0.6) return "footnote";  // footnotes, affiliations, venue notes
  if (block.size < ctx.body * 0.92 && block.top > page.height * 0.7 &&
      (/^([\d*†‡§¶]|\s)/.test(t) || /^(corresponding|equal contribution|work done|code (is )?available|preprint|proceedings of|copyright)/i.test(t) || /@|https?:\/\//.test(t))) return "footnote";
  if (block.size < ctx.body * 0.86) return "figtext";
  if (words < 4) return "figtext";
  return "paragraph";
}

function headingLevel(text) {
  var m = NUMBERED_HEADING.exec(text);
  if (!m) return 1;
  return (m[1].match(/\./g) || []).length + 1;
}

// ---- 6. figures, tables, algorithms ----
function isBarrier(block, body) {
  return (block.kind === "paragraph" && block.lines.length >= 2 && block.size >= body * 0.92) ||
    (block.kind === "heading" && NUMBERED_HEADING.test(block.text)) || block.kind === "caption";
}

function captionKind(word) {
  if (/^tab/i.test(word)) return "table";
  if (/^alg/i.test(word)) return "algorithm";
  return "figure";
}

function findRegions(pageInfo, ctx) {
  var regions = [];
  pageInfo.blocks.forEach(function (caption) {
    if (caption.kind !== "caption") return;
    var m = CAPTION.exec(caption.text);
    var kind = captionKind(m[1]);
    var full = caption.col === "F" || caption.col === "S" || (caption.x1 - caption.x0) > pageInfo.width * 0.6;
    var span = full ? [ctx.marginLeft, ctx.marginRight] : ctx.bounds[caption.col];
    var others = pageInfo.blocks.filter(function (b) {
      return b !== caption && b.x1 > span[0] + 4 && b.x0 < span[1] - 4 && b.kind !== "furniture";
    });
    function above() {
      var barrier = others.filter(function (b) { return b.bottom <= caption.top + 1 && isBarrier(b, ctx.body); })
        .sort(function (a, b) { return b.bottom - a.bottom; })[0];
      var edge = pageInfo.blocks.filter(function (b) { return b.kind === "furniture" && b.bottom < caption.top && b.top < pageInfo.height * 0.1; })
        .reduce(function (top, b) { return Math.max(top, b.bottom + 4); }, pageInfo.height * 0.06);
      var top = barrier ? barrier.bottom + 2 : Math.min(ctx.contentTop, edge);
      return caption.top - top > 24 ? [top, caption.bottom] : null;
    }
    function below() {
      var barrier = others.filter(function (b) { return b.top >= caption.bottom - 1 && isBarrier(b, ctx.body); })
        .sort(function (a, b) { return a.top - b.top; })[0];
      var bottom = barrier ? barrier.top - 2 : Math.max(ctx.contentBottom, pageInfo.height * 0.94);
      return bottom - caption.bottom > 24 ? [caption.top, bottom] : null;
    }
    var vertical = kind === "figure" ? above() || below() : below() || above();
    if (!vertical) vertical = [caption.top, caption.bottom];
    var rect = { x0: span[0] - 2, x1: span[1] + 2, top: vertical[0], bottom: vertical[1] };
    pageInfo.blocks.forEach(function (b) {
      if (b === caption || (b.kind === "heading" && NUMBERED_HEADING.test(b.text))) return;
      var inside = b.top >= rect.top - 2 && b.bottom <= rect.bottom + 2 && b.x0 >= rect.x0 - 2 && b.x1 <= rect.x1 + 2;
      if (inside && b.kind !== "caption") b.kind = kind === "algorithm" ? "algorithm" : kind === "table" ? "table" : "figtext";
    });
    var label = m[2].replace(/^([A-Z])\.?(\d)/, "$1.$2");
    var imageTop = rect.top, imageBottom = rect.bottom;
    if (caption.top - rect.top > 24) imageBottom = caption.top - 6;
    else if (rect.bottom - caption.bottom > 24) imageTop = caption.bottom + 6;
    regions.push({ kind: kind, label: label, page: pageInfo.number, caption: caption.text, captionKey: caption.key,
      imageRect: ctx.toRect(rect.x0, imageTop, rect.x1, imageBottom),
      rect: ctx.toRect(rect.x0, rect.top, rect.x1, rect.bottom) });
  });
  return regions;
}

// ---- 7. whole document ----
export function analyzeDocument(pages) {
  var all = [];
  var infos = pages.map(function (page, i) {
    page.number = i + 1;
    var lines = pageLines(page);
    all.push.apply(all, lines);
    return { number: i + 1, width: page.width, height: page.height, rawLines: lines };
  });
  var body = median(all.filter(function (l) { return l.text.length > 30; }).map(function (l) { return l.size; }));
  // repeated headers/footers: same text (digits masked) near the edge on 3+ pages
  var counts = {};
  all.forEach(function (l) {
    var page = infos[l.page - 1];
    if (l.top < page.height * 0.09 || l.bottom > page.height * 0.92) {
      var key = l.text.replace(/\d+/g, "#");
      counts[key] = (counts[key] || 0) + 1;
    }
  });
  var fonts = {};
  all.forEach(function (line) { line.runs.forEach(function (run) { if (run.font && run.size >= body * 0.95) fonts[run.font] = (fonts[run.font] || 0) + run.str.length; }); });
  var bodyFont = Object.keys(fonts).sort(function (a, b) { return fonts[b] - fonts[a]; })[0];
  var repeated = new Set(Object.keys(counts).filter(function (k) { return counts[k] >= 3; }));
  var doc = { body: body, pages: [], blocks: [], regions: [], equations: [], sections: [] };
  infos.forEach(function (info) {
    var ordered = orderLines(info.rawLines, info.width);
    var bounds = { F: [0, info.width], S: [0, info.width] };
    ["L", "R", "S"].forEach(function (col) { bounds[col] = columnBounds(ordered.lines, col, info.width); });
    if (!ordered.twoColumn) bounds.S = columnBounds(ordered.lines, "S", info.width);
    var content = ordered.lines.filter(function (l) { return l.top > info.height * 0.06 && l.bottom < info.height * 0.95; });
    var ctx = {
      body: body, bodyFont: bodyFont, repeated: repeated, page: info, bounds: bounds,
      marginLeft: Math.min.apply(null, content.map(function (l) { return l.x0; }).concat([info.width * 0.1])),
      marginRight: Math.max.apply(null, content.map(function (l) { return l.x1; }).concat([info.width * 0.9])),
      contentTop: content.length ? Math.min.apply(null, content.map(function (l) { return l.top; })) : 0,
      contentBottom: content.length ? Math.max.apply(null, content.map(function (l) { return l.bottom; })) : info.height,
      toRect: function (x0, top, x1, bottom) {
        return [Math.max(0, x0 / info.width), Math.max(0, top / info.height), Math.min(1, x1 / info.width), Math.min(1, bottom / info.height)];
      }
    };
    var blocks = makeBlocks(ordered.lines, ctx);
    blocks.forEach(function (b) {
      b.kind = classify(b, ctx);
      if (b.kind === "furniture" || b.kind === "paragraph") {
        if (repeated.has(b.text.replace(/\d+/g, "#")) && b.lines.length <= 2) b.kind = "furniture";
      }
      b.page = info.number;
      b.key = info.number + ":" + hashText(compact(b.text)).slice(0, 10);
      b.rect = ctx.toRect(b.x0, b.top, b.x1, b.bottom);
      b.lines.forEach(function (l) {
        l.rect = ctx.toRect(l.x0, l.top, l.x1, l.bottom);
        l.runs.forEach(function (r) { r.rect = ctx.toRect(r.x0, r.top, r.x1, r.bottom); });
      });
    });
    var pageInfo = { number: info.number, width: info.width, height: info.height, blocks: blocks, twoColumn: ordered.twoColumn, lines: ordered.lines };
    doc.regions.push.apply(doc.regions, findRegions(pageInfo, ctx));
    groupEquations(blocks, body, info).forEach(function (eq) { eq.page = info.number; doc.equations.push(eq); });
    doc.pages.push(pageInfo);
    doc.blocks.push.apply(doc.blocks, blocks);
  });
  markFrontMatter(doc);
  buildSections(doc);
  mergeContinuations(doc);
  doc.blocks.forEach(function (b) {
    b.translatable = (b.kind === "paragraph" || b.kind === "heading" || b.kind === "caption" || b.kind === "title") && !b.reference;
    if (b.translatable) {
      b.sentences = b.kind === "paragraph" || b.kind === "caption" ? splitSentences(b.text) : [b.text];
      // the key covers the sentence split too, so a better splitter never reuses a misaligned translation
      var oldKey = b.key;
      b.key = b.page + ":" + hashText(b.sentences.map(compact).join("␞")).slice(0, 10);
      if (b.kind === "caption") doc.regions.forEach(function (r) { if (r.captionKey === oldKey) r.captionKey = b.key; });
    }
  });
  doc.sections.forEach(function (sec) { sec.keys = doc.blocks.filter(function (b) { return b.sectionId === sec.id && b.kind !== "merged"; }).map(function (b) { return b.key; }); });
  return doc;
}

// Display math often comes out as several fragments (numerator, denominator, number). Merge neighbours into one equation.
function groupEquations(blocks, body, page) {
  var eqs = blocks.filter(function (b) { return b.kind === "equation"; }).sort(function (a, b) { return a.col.localeCompare(b.col) || a.top - b.top; });
  var groups = [];
  function numbered(b) { return b.lines.some(function (l) { var m = EQ_NUMBER.exec(l.text); return m && m[1] !== "0"; }); }
  eqs.forEach(function (b) {
    var last = groups[groups.length - 1];
    if (last && b.col === last.blocks[0].col && b.top - last.bottom < body * 1.8 && !(last.numbered && numbered(b))) {
      last.numbered = last.numbered || numbered(b);
      last.blocks.push(b);
      last.bottom = Math.max(last.bottom, b.bottom);
      last.x0 = Math.min(last.x0, b.x0);
      last.x1 = Math.max(last.x1, b.x1);
    } else groups.push({ blocks: [b], top: b.top, bottom: b.bottom, x0: b.x0, x1: b.x1, numbered: numbered(b) });
  });
  // Fractions and large operators can be isolated runs, not complete math lines.
  blocks.filter(function (b) { return b.kind !== "equation" && b.lines.length <= 2 &&
    /^(figtext|table|footnote)$/.test(b.kind) && !/[A-Za-z]{4,}/.test(b.text); }).forEach(function (b) {
    var near = groups.filter(function (g) { return g.blocks[0].col === b.col &&
      Math.max(0, g.top - b.bottom, b.top - g.bottom) < body * 0.9 && Math.abs((g.top + g.bottom - b.top - b.bottom) / 2) < body * 2; })
      .sort(function (a, c) { return Math.abs(a.top - b.top) - Math.abs(c.top - b.top); })[0];
    if (near) { near.blocks.push(b); near.top = Math.min(near.top, b.top); near.bottom = Math.max(near.bottom, b.bottom); }
  });
  return groups.map(function (g) {
    var number = null;
    g.blocks.forEach(function (b) {
      b.lines.forEach(function (l) { var m = EQ_NUMBER.exec(l.text); if (m && m[1] !== "0") number = m[1]; });
    });
    var rect = [Math.min.apply(null, g.blocks.map(function (b) { return b.rect[0]; })), Math.min.apply(null, g.blocks.map(function (b) { return b.rect[1]; })),
      Math.max.apply(null, g.blocks.map(function (b) { return b.rect[2]; })), Math.max.apply(null, g.blocks.map(function (b) { return b.rect[3]; }))];
    rect = [Math.max(0, rect[0] - 3 / page.width), Math.max(0, rect[1] - 3 / page.height), Math.min(1, rect[2] + 3 / page.width), Math.min(1, rect[3] + 3 / page.height)];
    return { number: number, text: g.blocks.map(function (b) { return b.text; }).join("\n"), rect: rect, key: g.blocks[0].key,
      size: g.blocks.reduce(function (n, b) { return n + b.text.length; }, 0) };
  }).filter(function (e) { return e.number || e.size >= 12; });
}

function sectionNumber(text) {
  var m = /^(\d{1,2})(?:\.\d+)*\.?\s/.exec(text);
  return m ? Number(m[1]) : null;
}

// Docling supplies semantic boundaries and reading order; PDF.js supplies rendering and text selection.
export function analyzeDocling(pages, layout) {
  var source = analyzeDocument(pages), doc = { body: source.body, pages: [], blocks: [], regions: [], equations: [], sections: [], engine: "docling" };
  layout.pages.forEach(function (page) {
    var info = { number: page.number, width: page.width, height: page.height, blocks: [], lines: source.pages[page.number - 1].lines };
    var ordered = [], left = [], right = [];
    function flush() { ordered.push(...left, ...right); left = []; right = []; }
    page.blocks.slice().sort(function (a, b) { return a.rect[1] - b.rect[1] || a.rect[0] - b.rect[0]; }).forEach(function (item) {
      if (item.rect[2] <= 0.56) left.push(item);
      else if (item.rect[0] >= 0.44) right.push(item);
      else { flush(); ordered.push(item); }
    });
    flush();
    ordered.forEach(function (item) {
      var r = item.rect, text = item.text;
      var lines = info.lines.filter(function (line) { var x = (line.x0 + line.x1) / (2 * info.width), y = (line.top + line.bottom) / (2 * info.height); return x >= r[0] && x <= r[2] && y >= r[1] && y <= r[3]; });
      if (text === null) text = lines.map(function (line) { return line.text; }).join(" ");
      var block = { text: text || "", kind: item.kind, page: page.number, rect: r, parts: [{ page: page.number, rect: r }], lines: lines,
        semantic: true, sourceRef: item.ref, captions: item.captions, col: r[2] <= 0.55 ? "L" : r[0] >= 0.45 ? "R" : "F",
        x0: r[0] * info.width, x1: r[2] * info.width, top: r[1] * info.height, bottom: r[3] * info.height,
        size: lines.length ? median(lines.map(function (line) { return line.size; })) : doc.body };
      block.key = block.page + ":" + hashText(compact(block.text)).slice(0, 10);
      info.blocks.push(block); doc.blocks.push(block);
    });
    doc.pages.push(info);
  });
  markFrontMatter(doc);
  buildSections(doc);
  doc.blocks.forEach(function (block) {
    block.translatable = /^(paragraph|heading|caption|title)$/.test(block.kind) && !block.reference && !!block.text.trim();
    block.sentences = /^(paragraph|caption)$/.test(block.kind) ? splitSentences(block.text) : [block.text];
    block.key = block.page + ":" + hashText(block.sentences.map(compact).join("␞")).slice(0, 10);
    if (block.kind === "equation") {
      var numbers = block.text.match(/\(\s*(\d{1,3}[a-z]?|[A-Z]\.\d{1,3})\s*\)/g);
      var number = numbers && EQ_NUMBER.exec(numbers[numbers.length - 1]);
      doc.equations.push({ page: block.page, number: number ? number[1] : null, text: block.text, rect: block.rect, key: block.key });
    }
  });
  doc.pages.forEach(function (page) {
    var graphics = page.blocks.filter((b) => b.kind === "figure" || b.kind === "table");
    var captions = page.blocks.filter((b) => b.kind === "caption");
    var claimed = new Set(graphics.flatMap((b) => b.captions));
    graphics.forEach(function (block) {
      var caption = captions.find((b) => block.captions.includes(b.sourceRef));
      // Docling sometimes leaves a nearby caption unlinked. Only pair unambiguous orphans.
      if (!block.captions.length && graphics.filter((b) => b.kind === block.kind && !b.captions.length).length === 1) {
        var nearby = captions.filter(function (b) {
          var label = CAPTION.exec(b.text);
          return !claimed.has(b.sourceRef) && label && captionKind(label[1]) === block.kind &&
            Math.min(b.x1, block.x1) > Math.max(b.x0, block.x0) &&
            Math.max(b.top - block.bottom, block.top - b.bottom) <= 2 * b.size;
        });
        if (nearby.length === 1) caption = nearby[0];
      }
      if (!caption) return;
      var label = CAPTION.exec(caption.text);
      if (!label) return;
      doc.regions.push({ kind: block.kind, page: page.number, label: label[2], caption: caption.text, captionKey: caption.key,
        imageRect: block.rect, rect: [Math.min(block.rect[0], caption.rect[0]), Math.min(block.rect[1], caption.rect[1]), Math.max(block.rect[2], caption.rect[2]), Math.max(block.rect[3], caption.rect[3])] });
    });
  });
  doc.sections.forEach(function (section) { section.keys = doc.blocks.filter(function (b) { return b.sectionId === section.id; }).map(function (b) { return b.key; }); });
  return doc;
}

// A paragraph cut by a column or page break continues in the next paragraph block: join them so sentences stay whole.
var BETWEEN = { furniture: 1, footnote: 1, figtext: 1, author: 1, table: 1, caption: 1, algorithm: 1 };
function mergeContinuations(doc) {
  var prev = null;
  doc.blocks.forEach(function (b) {
    b.parts = b.parts || [{ page: b.page, rect: b.rect }];
    if (BETWEEN[b.kind] || b.reference || (b.kind === "equation" && b.text.length <= 3)) return;
    if (b.kind !== "paragraph") { prev = null; return; }
    var open = prev && !/[.!?:;]["”’)\]]?$/.test(prev.text);
    var last = prev && prev.lines[prev.lines.length - 1];
    var moved = prev && (b.page === prev.page + 1 || (b.page === prev.page && b.col !== last.col));
    var adjacent = prev && b.page === prev.page && b.col === last.col && b.top - last.bottom < doc.body * 1.3;
    var continues = /-$/.test(prev ? prev.text : "") || /^[a-z(,;]/.test(b.text);
    if (open && (adjacent || (moved && continues)) && prev.sectionId === b.sectionId) {
      prev.text = /[A-Za-z]-$/.test(prev.text) ? prev.text + b.text : prev.text + " " + b.text;
      prev.lines = prev.lines.concat(b.lines);
      prev.parts.push({ page: b.page, rect: b.rect });
      b.kind = "merged";
      b.mergedInto = prev.key;
      return;
    }
    prev = b;
  });
  doc.blocks.forEach(function (b) {
    if (b.parts.length > 1) b.key = b.page + ":" + hashText(compact(b.text)).slice(0, 10);
  });
  doc.sections.forEach(function (s) { s.keys = doc.blocks.filter(function (b) { return b.sectionId === s.id && b.kind !== "merged"; }).map(function (b) { return b.key; }); });
}

function markFrontMatter(doc) {
  var first = doc.pages[0];
  if (!first) return;
  var abstractAt = first.blocks.findIndex(function (b) { return /^abstract\b/i.test(b.text); });
  var candidates = first.blocks.slice(0, abstractAt > 0 ? abstractAt : Math.min(8, first.blocks.length));
  var title = candidates.filter(function (b) { return b.kind !== "furniture" && b.top < first.height * 0.4; })
    .sort(function (a, b) { return b.size - a.size; })[0];
  if (title && title.size > doc.body * 1.2) title.kind = "title";
  if (abstractAt > 0) {
    first.blocks.slice(0, abstractAt).forEach(function (b) { if (b !== title && b.kind !== "furniture") b.kind = "author"; });
    var head = first.blocks[abstractAt];
    if (head.text.length > 12 && head.kind !== "heading") {
      // "Abstract—We propose ..." run-in heading: keep it as a paragraph
    } else head.kind = "heading";
  }
  // emails / affiliations before the first heading
  first.blocks.forEach(function (b) { if (/@|\{.*\}/.test(b.text) && b.kind === "paragraph" && b.lines.length <= 4 && b.top < first.height * 0.45) b.kind = "author"; });
}

function buildSections(doc) {
  var section = { id: "s0", title: "앞부분", level: 1, page: 1, keys: [] }, inReferences = false, refStart = null;
  var lastMajor = null, inAppendix = false;
  doc.sections.push(section);
  doc.blocks.forEach(function (b) {
    if (b.kind === "heading") {
      var major = sectionNumber(b.text);
      if (major != null && (major > 40 || (lastMajor != null && major < lastMajor && !inAppendix))) b.kind = "figtext"; // "2.5 Pro" in a table
      else if (major != null && inAppendix && b.size < doc.body * 1.04) b.kind = "paragraph"; // numbered list inside an appendix
      else if (major != null) lastMajor = major;
      if (/^(appendix|appendices|[A-H](\.\d+)*\.?\s+[A-Z])/i.test(b.text) && !/^[A-H]\s+[a-z]/.test(b.text)) inAppendix = inAppendix || inReferences || /^appendix/i.test(b.text);
    }
    if (b.kind === "heading" || b.kind === "title") {
      var appendixLike = /^(appendix|appendices|[A-H](\.\d+)*\.?\s+[A-Z])/i.test(b.text) || /checklist/i.test(b.text);
      if (inReferences && !appendixLike) { b.kind = "reference"; b.reference = true; section.keys.push(b.key); return; }
      if (b.kind === "heading") {
        inReferences = REFERENCES.test(b.text);
        if (inReferences && !refStart) refStart = { page: b.page, top: b.rect[1] };
        section = { id: "s" + doc.sections.length, title: b.text, level: headingLevel(b.text), page: b.page, top: b.rect[1], keys: [], references: inReferences };
        doc.sections.push(section);
      }
    } else if (inReferences && b.kind !== "furniture") {
      b.reference = true;
    }
    b.sectionId = section.id;
    section.keys.push(b.key);
  });
  if (!doc.sections[0].keys.some(function (k) { return true; })) doc.sections.shift();
  doc.refStart = refStart;
}

