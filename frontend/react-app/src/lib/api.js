export function apiBaseUrl() {
  if (import.meta.env.VITE_API_URL) return import.meta.env.VITE_API_URL.replace(/\/$/, "");
  return `${window.location.protocol}//${window.location.hostname || "localhost"}:8000`;
}

export function websocketUrl() {
  if (import.meta.env.VITE_WS_URL) return import.meta.env.VITE_WS_URL;
  return `${window.location.protocol === "https:" ? "wss" : "ws"}://${window.location.hostname || "localhost"}:8000/ws/voice`;
}

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

function detailMessage(body, status) {
  const detail = body?.detail;
  if (typeof detail === "string") return detail;
  // FastAPI validation errors: [{loc, msg}, ...]
  if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg.replace(/^Value error, /, "");
  return `Request failed (HTTP ${status})`;
}

// JSON request to the backend. Throws ApiError with the server's message.
export async function apiFetch(path, { token, method = "GET", body } = {}) {
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = `Bearer ${token}`;
  let response;
  try {
    response = await fetch(`${apiBaseUrl()}${path}`, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "Cannot reach the server. Check that the backend is running.");
  }
  let data = null;
  try {
    data = await response.json();
  } catch {
    // empty or non-JSON body
  }
  if (!response.ok) throw new ApiError(response.status, detailMessage(data, response.status));
  return data;
}
