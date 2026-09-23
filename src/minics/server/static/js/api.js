/* MiniCS API client + SSE helpers (no build step, plain ES2020). */
(function () {
  "use strict";

  async function handle(response) {
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      const body = await response.json();
      if (!response.ok || body.ok === false) {
        const error = new Error(body.error || `HTTP ${response.status}`);
        error.status = response.status;
        error.body = body;
        throw error;
      }
      return body.data !== undefined ? body.data : body;
    }
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.text();
  }

  async function request(method, path, options) {
    options = options || {};
    const init = { method, headers: {} };
    if (options.json !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(options.json);
    } else if (options.form !== undefined) {
      init.body = options.form;
    }
    const response = await fetch(path, init);
    return handle(response);
  }

  async function upload(path, files, fields) {
    const form = new FormData();
    Array.from(files).forEach((file) => form.append("files", file, file.name));
    Object.entries(fields || {}).forEach(([key, value]) => {
      if (Array.isArray(value)) value.forEach((item) => form.append(key, item));
      else if (value !== undefined && value !== null) form.append(key, value);
    });
    const response = await fetch(path, { method: "POST", body: form });
    return handle(response);
  }

  function parseSSE(chunk) {
    const events = [];
    chunk.split("\n\n").forEach((block) => {
      if (!block.trim()) return;
      let data = "";
      block.split("\n").forEach((line) => {
        if (line.startsWith("data:")) data += line.slice(5).trim();
      });
      if (!data) return;
      try {
        events.push(JSON.parse(data));
      } catch (error) {
        /* ignore malformed frames / keep-alives */
      }
    });
    return events;
  }

  async function stream(path, body, onEvent, signal) {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
      signal,
    });
    if (!response.ok || !response.body) {
      const text = await response.text().catch(() => "");
      throw new Error(text || `HTTP ${response.status}`);
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let index;
      while ((index = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, index);
        buffer = buffer.slice(index + 2);
        parseSSE(frame + "\n\n").forEach((event) => onEvent && onEvent(event));
      }
    }
  }

  function events(onEvent, afterId) {
    const source = new EventSource(`/api/events?after=${afterId || 0}`);
    source.onmessage = (message) => {
      try {
        onEvent(JSON.parse(message.data));
      } catch (error) {
        /* ignore */
      }
    };
    source.onerror = () => {
      /* EventSource reconnects automatically */
    };
    return source;
  }

  window.API = {
    get: (path) => request("GET", path),
    post: (path, json) => request("POST", path, { json }),
    put: (path, json) => request("PUT", path, { json }),
    patch: (path, json) => request("PATCH", path, { json }),
    del: (path, json) => request("DELETE", path, { json }),
    upload,
    stream,
    events,
  };
})();
