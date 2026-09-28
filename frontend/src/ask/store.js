import { useSyncExternalStore } from "react";
import { ApiError, api } from "../api";

// The Ask a question history, kept outside the panel so it survives switching tabs (the panel is
// unmounted when you leave the tab, and its own state went with it) and a request still running when
// you leave lands when it returns. Copied to sessionStorage so a page refresh keeps it too; that is
// per browser tab and gone when the tab closes, and clearAskHistory() empties it on login and logout
// so the next person at the same browser never sees someone else's answers.

const KEY = "bdp_ask_history";
const MAX_ANSWERS = 20;

function load() {
  try {
    const saved = JSON.parse(sessionStorage.getItem(KEY));
    // A question that was still running when the page reloaded will never get its answer: drop it.
    return Array.isArray(saved) ? saved.filter((a) => !a.pending) : [];
  } catch {
    return [];
  }
}

let state = { answers: load(), busy: false };
let nextId = state.answers.reduce((max, a) => Math.max(max, a.id || 0), 0) + 1;
const listeners = new Set();

function setState(update) {
  state = { ...state, ...update(state) };
  try {
    sessionStorage.setItem(KEY, JSON.stringify(state.answers.filter((a) => !a.pending)));
  } catch {
    /* storage full or blocked: the history still works for this visit */
  }
  listeners.forEach((listener) => listener());
}

function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useAskHistory() {
  return useSyncExternalStore(subscribe, () => state);
}

/** Asks (body = { question }) or refines an existing answer in place (replaceId + { question, query, filters }). */
export async function runAsk(body, replaceId) {
  const id = replaceId ?? nextId++;
  setState((s) => ({
    busy: true,
    answers: replaceId
      ? s.answers.map((a) => (a.id === id ? { ...a, pending: true } : a))
      : [{ id, question: body.question, pending: true }, ...s.answers].slice(0, MAX_ANSWERS),
  }));
  let result;
  try {
    result = { id, ...(await api.ask(body)) };
  } catch (e) {
    const unavailable = e instanceof ApiError && e.status === 503;
    result = { id, question: body.question, status: "error", message: unavailable ? "Ask a question isn't available right now - the model server isn't running." : e.message };
  }
  setState((s) => ({ busy: false, answers: s.answers.map((a) => (a.id === id ? result : a)) }));
}

export function clearAskHistory() {
  setState(() => ({ answers: [], busy: false }));
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    /* ignore */
  }
}
