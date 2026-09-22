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

async function send(path, { method = "GET", body } = {}) {
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
  return response;
}

async function request(path, options) {
  return (await send(path, options)).json();
}

function query(params = {}) {
  const usp = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") usp.set(key, value);
  }
  const text = usp.toString();
  return text ? `?${text}` : "";
}

/**
 * Downloads a file the API generates (Excel, PDF): fetch with the login token, then hand the browser a temporary
 * link. A plain <a href> can't be used because it wouldn't carry the Authorization header.
 */
export async function download(path, { method = "GET", fallbackName = "download" } = {}) {
  const response = await send(path, { method });
  const blob = await response.blob();
  const match = /filename="?([^";]+)"?/i.exec(response.headers.get("Content-Disposition") || "");
  const name = match ? match[1] : fallbackName;
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return name;
}

export const api = {
  login: (email, password) => request("/auth/login", { method: "POST", body: { email, password } }),

  // Screen 1
  kpiLatest: () => request("/kpi-summary/latest"),
  kpiHistory: (days = 730) => request(`/kpi-summary/history?days=${days}`),

  // Screen 2 and the drill-downs from Screen 5
  portfolioOverview: () => request("/portfolio/overview"),
  breakdown: (dimension) => request(`/portfolio/breakdown${query({ dimension })}`),
  stageSummary: () => request("/portfolio/stage-summary"),
  topExposures: () => request("/portfolio/top-exposures"),
  ageing: () => request("/portfolio/ageing"),
  ltvDistribution: () => request("/portfolio/ltv-distribution"),
  loans: (params) => request(`/portfolio/loans${query(params)}`),
  customers: (params) => request(`/portfolio/customers${query(params)}`),
  exportPortfolio: () => download("/portfolio/export.xlsx", { fallbackName: "portfolio_credit_risk.xlsx" }),

  // Screen 4
  scenarioSnapshot: () => request("/scenario/snapshot"),
  savedScenarios: () => request("/scenario/saved"),
  saveScenario: (body) => request("/scenario/save", { method: "POST", body }),

  // Screen 5
  branches: () => request("/performance/branches"),
  segments: () => request("/performance/segments"),
  products: () => request("/performance/products"),
  channels: () => request("/performance/channels"),
  exportPerformance: () => download("/performance/export.xlsx", { fallbackName: "branch_segment_performance.xlsx" }),

  // Screen 3
  reports: () => request("/reports"),
  report: (id) => request(`/reports/${id}`),
  drill: (id, lineCode) => request(`/reports/${id}/drill/${encodeURIComponent(lineCode)}`),
  exportReport: (id, kind) => download(`/reports/${id}/export/${kind}`, { method: "POST", fallbackName: `report.${kind === "pdf" ? "pdf" : "xlsx"}` }),

  // Screen 6 - everything except task state/actions, which go straight to Tasklist (tasklistApi.js)
  exceptionDetail: (params) => request(`/workflow/exceptions/detail${query(params)}`),
  exceptionComments: (params) => request(`/workflow/exceptions/comments${query(params)}`),
  addExceptionComment: (body) => request("/workflow/exceptions/comments", { method: "POST", body }),
  logTaskCompletion: (body) => request("/workflow/exceptions/task-completions", { method: "POST", body }),
  auditLog: (params) => request(`/workflow/audit-log${query(params)}`),
  breaches: (params) => request(`/workflow/breaches${query(params)}`),
  workflowStats: () => request("/workflow/stats"),

  // Reconciliation tab (specs/multi-source-reconciliation.md) - standalone from Screen 6/Camunda
  reconciliationExceptions: (params) => request(`/reconciliation${query(params)}`),
  reconciliationSummary: () => request("/reconciliation/summary"),
  resolveReconciliation: (id, body) => request(`/reconciliation/${id}/resolve`, { method: "POST", body }),
};
