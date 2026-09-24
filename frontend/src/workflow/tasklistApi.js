// Thin client for Camunda Tasklist's REST API v1 - called directly from the browser, per
// CLAUDE.md's Workflow Engine Decision ("React's Screen 6 calls Camunda Tasklist's REST API
// rather than a custom FastAPI workflow endpoint"). specs/screen-06-report-workflow.md section 2.
//
// Base path proxied through Vite's dev server as /tasklist -> localhost:8082 (see
// frontend/vite.config.js) so the browser only ever talks to one origin.
//
// Verified live against the local stack (2026-09-22), endpoint-by-endpoint, using curl against
// Tasklist's own /v3/api-docs (not guessed from memory): ZEEBE_AUTHENTICATION_MODE=none only
// disables auth on the Zeebe gRPC gateway - Tasklist's own webapp has a SEPARATE session-cookie
// login (Spring Security, not HTTP Basic), seeded with a default demo/demo user; every /v1 call
// 401s without first POSTing /api/login and picking up its Set-Cookie. The assign endpoint is
// /assign, not /claim. /complete wants {variables: [{name, value}]} with each value
// JSON-encoded, not a plain {name: value} object - a plain object 400s. All three
// candidateGroups (fraud-investigation/compliance/operations) and all three outcomes
// (APPROVED/REJECTED/CORRECTED, including a CORRECTED value round-tripping into review_outcomes)
// were completed end-to-end through this exact request shape.
const BASE = "/tasklist";
const DEMO_USER = import.meta.env.VITE_TASKLIST_USER || "demo";
const DEMO_PASSWORD = import.meta.env.VITE_TASKLIST_PASSWORD || "demo";

class TasklistError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}

let session = null;

function login() {
  session = fetch(`${BASE}/api/login?username=${encodeURIComponent(DEMO_USER)}&password=${encodeURIComponent(DEMO_PASSWORD)}`, {
    method: "POST",
    credentials: "same-origin",
  }).then((r) => {
    if (!r.ok) {
      session = null;
      throw new TasklistError(r.status, "Couldn't log in to Tasklist (demo/demo). Check camunda/README.md.");
    }
  });
  return session;
}

async function call(path, { method = "GET", body, retried = false } = {}) {
  await (session || login());
  let response;
  try {
    response = await fetch(`${BASE}/v1${path}`, {
      method,
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new TasklistError(0, "Can't reach Tasklist. Check that the Camunda stack is running (camunda/README.md).");
  }
  // The session cookie can outlive Tasklist's in-memory session (e.g. after a container
  // restart); retry once with a fresh login before giving up.
  if (response.status === 401 && !retried) {
    session = null;
    return call(path, { method, body, retried: true });
  }
  if (!response.ok) {
    let detail = `Tasklist request failed (${response.status})`;
    try {
      const data = await response.json();
      detail = data.message || data.detail || detail;
    } catch {
      /* non-JSON error body */
    }
    throw new TasklistError(response.status, detail);
  }
  if (response.status === 204) return null;
  return response.json();
}

// specs/camunda-bpmn-process-design.md section 3's three candidate groups, plus the CFO
// reconciliation workflow's two (specs/cfo-reconciliation-workflow.md).
export const CANDIDATE_GROUPS = ["fraud-investigation", "compliance", "operations", "cfo", "reconciliation-team"];

/**
 * The stack has no Identity/Keycloak, so Tasklist tasks carry candidate GROUPS, not individual
 * assignable users - there's no per-login mapping from this app's seeded demo users (analyst,
 * reviewer, approver, admin) to fraud-investigation/compliance/operations
 * (specs/camunda-bpmn-process-design.md Open Item 2, still unresolved). For the POC, every
 * logged-in user can see and act on all three groups' tasks rather than being scoped to one -
 * flagged in the UI with an AssumptionBadge rather than silently narrowing access.
 */
// Requested inline via includeVariables rather than a separate getVariables call per row - one
// Tasklist round trip for the whole list instead of N+1.
const LIST_VARIABLES = ["recordType", "sourceTable", "recordKey", "flagLabel", "title", "severity", "dueDate", "accountId"];

// Tasklist returns 50 tasks per search unless asked otherwise, so page through with searchAfter
// until a short page: with more than 50 open tasks the rest were silently missing (live, 2026-09-25).
const PAGE_SIZE = 200;

export async function searchTasks({ state = "CREATED", candidateGroups = CANDIDATE_GROUPS } = {}) {
  const tasks = [];
  let searchAfter;
  for (;;) {
    const page = await call("/tasks/search", {
      method: "POST",
      body: { state, candidateGroups, pageSize: PAGE_SIZE, includeVariables: LIST_VARIABLES.map((name) => ({ name })), ...(searchAfter && { searchAfter }) },
    });
    tasks.push(...page);
    if (page.length < PAGE_SIZE) break;
    searchAfter = page[page.length - 1].sortValues;
  }
  return tasks.map((t) => {
    const vars = {};
    for (const v of t.variables || []) {
      try {
        vars[v.name] = JSON.parse(v.value);
      } catch {
        vars[v.name] = v.value;
      }
    }
    return { ...t, vars };
  });
}

export function getTask(taskId) {
  return call(`/tasks/${encodeURIComponent(taskId)}`);
}

export async function getVariables(taskId) {
  const vars = await call(`/tasks/${encodeURIComponent(taskId)}/variables/search`, { method: "POST", body: {} });
  const byName = {};
  for (const v of vars) {
    try {
      byName[v.name] = JSON.parse(v.value);
    } catch {
      byName[v.name] = v.value;
    }
  }
  return byName;
}

// The endpoint is /assign, not /claim - verified against the live instance (2026-09-22).
// No `assignee` in the body: Tasklist then self-assigns to whoever the TASKLIST-SESSION cookie
// belongs to (always DEMO_USER here - there's no per-app-user identity in Tasklist, see this
// file's header comment). Passing our own app's user_id as the assignee 403s ("doesn't have the
// permission to assign another user to this task") since that's a different identity than DEMO_USER
// - confirmed live (2026-09-23), and that failure was getting silently swallowed by the caller's
// best-effort try/catch, so the task stayed unassigned and only surfaced later as Tasklist's
// "Task is not assigned" 400 on /complete.
export function claimTask(taskId) {
  return call(`/tasks/${encodeURIComponent(taskId)}/assign`, { method: "PATCH", body: {} });
}

// Verified live: /complete wants { variables: [{name, value}] }, value JSON-encoded (Zeebe
// variables are stored as JSON) - a plain { name: value } map 400s.
//
// A failed /complete is checked against the task itself: if Zeebe finished it anyway (the reply was
// lost or timed out while the broker was slow, and a second Submit then got "Task is not active" -
// live, 2026-09-25), the decision went through, so it counts as done rather than as an error.
export async function completeTask(taskId, variables) {
  const encoded = Object.entries(variables).map(([name, value]) => ({ name, value: JSON.stringify(value) }));
  try {
    return await call(`/tasks/${encodeURIComponent(taskId)}/complete`, { method: "PATCH", body: { variables: encoded } });
  } catch (err) {
    const task = await getTask(taskId).catch(() => null);
    if (task?.taskState === "COMPLETED") return task;
    throw err;
  }
}

export { TasklistError };
