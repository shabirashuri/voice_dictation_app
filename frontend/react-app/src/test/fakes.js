import { vi } from "vitest";

// Minimal stand-in for the browser WebSocket, driven by the test.
export class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSED = 3;
  static instances = [];

  constructor(url) {
    this.url = url;
    this.readyState = FakeWebSocket.CONNECTING;
    this.sent = [];
    FakeWebSocket.instances.push(this);
  }

  send(data) {
    this.sent.push(JSON.parse(data));
  }

  close() {
    if (this.readyState === FakeWebSocket.CLOSED) return;
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.();
  }

  // --- test controls ---
  open() {
    this.readyState = FakeWebSocket.OPEN;
    return this.onopen?.();
  }

  serverSend(message) {
    this.onmessage?.({ data: JSON.stringify(message) });
  }

  sentTypes() {
    return this.sent.map((m) => m.type).filter(Boolean);
  }
}

class FakeAudioContext {
  sampleRate = 48000;
  destination = {};
  createMediaStreamSource() {
    return { connect() {} };
  }
  createScriptProcessor() {
    return { connect() {}, disconnect() {}, onaudioprocess: null };
  }
  close() {
    return Promise.resolve();
  }
}

export function installBrowserFakes() {
  FakeWebSocket.instances = [];
  vi.stubGlobal("WebSocket", FakeWebSocket);
  vi.stubGlobal("AudioContext", FakeAudioContext);
  vi.stubGlobal("fetch", vi.fn());
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: {
      getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop() {} }] }),
    },
  });
}

export function lastSocket() {
  return FakeWebSocket.instances.at(-1);
}

export function jsonResponse(status, body) {
  return { ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) };
}

// Route fetch calls by "METHOD /path" to canned responses (or functions of the request).
export function routeFetch(routes) {
  fetch.mockImplementation(async (url, options = {}) => {
    const path = new URL(url).pathname;
    const key = `${options.method || "GET"} ${path}`;
    const route = routes[key];
    if (!route) return jsonResponse(404, { detail: `no fake route for ${key}` });
    const [status, body] = typeof route === "function" ? route(options) : route;
    return jsonResponse(status, body);
  });
}
