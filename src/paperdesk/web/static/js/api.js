import { locale, t } from "./i18n.js";
export class ApiError extends Error {
  constructor(message, status, code) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function readCompletion(response, onDelta) {
  var reader = response.body.getReader(), decoder = new TextDecoder(), pending = "";
  try {
    while (true) {
      var chunk = await reader.read();
      if (chunk.done) break;
      pending += decoder.decode(chunk.value, { stream: true });
      var end;
      while ((end = pending.indexOf("\n")) >= 0) {
        var event = JSON.parse(pending.slice(0, end));
        pending = pending.slice(end + 1);
        if (event.error) throw new ApiError(event.error.message, response.status, event.error.code);
        if ("result" in event) return event.result;
        if (typeof event.delta === "string") onDelta(event.delta);
      }
    }
    throw new ApiError(t("응답이 끝나기 전에 연결이 끊겼어요."), 0, "incomplete");
  } finally {
    reader.releaseLock();
  }
}

// Every request carries X-Paperdesk so the local server can reject requests from other websites.
export class ApiClient {
  async request(method, path, body, headers, keepalive, onDelta) {
    var options = { method: method, headers: Object.assign({ "X-Paperdesk": "1", "X-Paperdesk-Lang": locale() }, headers || {}) };
    if (keepalive) options.keepalive = true;
    if (body !== undefined) {
      if (body instanceof Blob || body instanceof ArrayBuffer) {
        options.body = body;
      } else {
        options.body = JSON.stringify(body);
        options.headers["Content-Type"] = "application/json";
      }
    }
    var response;
    try {
      response = await fetch(path, options);
    } catch (error) {
      throw new ApiError(t("앱 서버에 연결하지 못했어요."), 0, "offline");
    }
    if (response.ok && onDelta && response.headers.get("Content-Type")?.includes("application/x-ndjson")) {
      return readCompletion(response, onDelta);
    }
    var data = null;
    try { data = await response.json(); } catch (error) { data = null; }
    if (!response.ok) {
      var detail = data && data.error ? data.error : {};
      throw new ApiError(detail.message || t("요청에 실패했어요 ({status})", { status: response.status }), response.status, detail.code);
    }
    return data;
  }

  get(path) { return this.request("GET", path); }
  post(path, body, onDelta) {
    return this.request("POST", path, body === undefined ? {} : body,
      onDelta ? { Accept: "application/x-ndjson" } : null, false, onDelta);
  }
  put(path, body) { return this.request("PUT", path, body); }
  patch(path, body) { return this.request("PATCH", path, body); }
  del(path) { return this.request("DELETE", path); }

  upload(file, folderId) {
    var query = folderId ? "?folder=" + encodeURIComponent(folderId) : "";
    return this.request("POST", "/api/documents" + query, file,
      { "Content-Type": "application/pdf", "X-Filename": encodeURIComponent(file.name) });
  }
}
