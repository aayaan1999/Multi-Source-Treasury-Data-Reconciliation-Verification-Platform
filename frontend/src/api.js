// Thin fetch wrapper for the FastAPI backend. In dev the Vite proxy forwards /api to the backend
// (BASE stays ""); set VITE_API_URL when the API is served from another origin.
// A trailing slash on the configured address would produce "//api/v1/..."; strip it.
const BASE = (import.meta.env.VITE_API_URL ?? "").replace(/\/+$/, "");
const TOKEN_KEY = "bdp_token";
const USER_KEY = "bdp_user";

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

// localStorage can throw (private windows, blocked storage): the app must still work without it.
function safeGet(key) {
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}
function safeSet(key, value) {
  try {
    if (value == null) localStorage.removeItem(key);
    else localStorage.setItem(key, value);
  } catch {
    /* ignore */
  }
}

export const session = {
  token: () => safeGet(TOKEN_KEY),
  user: () => {
    try {
      return JSON.parse(safeGet(USER_KEY));
    } catch {
      return null;
    }
  },
  save: (token, user) => {
    safeSet(TOKEN_KEY, token);
    safeSet(USER_KEY, JSON.stringify(user));
  },
  clear: () => {
    safeSet(TOKEN_KEY, null);
    safeSet(USER_KEY, null);
  },
};

let onUnauthorized = () => {};
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn;
}

async function request(path, { method = "GET", body } = {}) {
  const headers = { Accept: "application/json" };
  const token = session.token();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  let response;
  try {
    response = await fetch(`${BASE}/api/v1${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiError(0, "Can't reach the server. Check that the API is running.");
  }

  if (response.status === 401 && path !== "/auth/login") onUnauthorized();
  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const data = await response.json();
      if (typeof data.detail === "string") detail = data.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(response.status, detail);
  }
  return response.json();
}

export const api = {
  login: (email, password) => request("/auth/login", { method: "POST", body: { email, password } }),
  kpiLatest: () => request("/kpi-summary/latest"),
  kpiHistory: (days = 730) => request(`/kpi-summary/history?days=${days}`),
};
