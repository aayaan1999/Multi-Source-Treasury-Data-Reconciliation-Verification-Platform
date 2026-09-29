import { useSyncExternalStore } from "react";
import { ApiError, api } from "../api";

// The Ask a question history. Each answer is saved on the server for the user who asked it
// (ask_history, GET /ask/history), so it comes back after logging out and in again or on another
// browser. Two lists:
//   answers   - asked (or reopened) since this login, shown in full
//   previous  - earlier saved answers, shown as a grid of tiles: the newest FIRST_PAGE, then PAGE_SIZE
//               more per "Show more"; opening a tile moves it up into `answers` without re-asking
// The store lives outside the panel so it survives switching tabs (the panel is unmounted when you
// leave the tab) and a request still running when you leave lands when it returns.
// resetAskHistory() empties only this browser's copy on login and logout, so the next person at the
// same browser never sees someone else's answers; clearAskHistory() deletes the saved list too.

export const FIRST_PAGE = 5;
export const PAGE_SIZE = 10;
const MAX_ANSWERS = 20;

const EMPTY = { answers: [], busy: false, previous: [], hasMore: false, loadingMore: false, historyError: null };
let state = EMPTY;
let nextId = 1;
let generation = 0;     // bumped on login/logout so a page arriving afterwards is dropped
let loaded = null;      // the first page is fetched once per login
const listeners = new Set();

function setState(update) {
  state = { ...state, ...update(state) };
  listeners.forEach((listener) => listener());
}

function subscribe(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useAskHistory() {
  return useSyncExternalStore(subscribe, () => state);
}

async function fetchPage(params) {
  const mine = generation;
  const page = await api.askHistory(params);
  if (mine !== generation) return;
  setState((s) => {
    const shown = new Set([...s.answers, ...s.previous].map((a) => a.history_id).filter(Boolean));
    const fresh = page.items.filter((a) => !shown.has(a.history_id)).map((a) => ({ ...a, id: nextId++ }));
    return { previous: [...s.previous, ...fresh], hasMore: page.has_more, historyError: null };
  });
}

/** The newest saved answers, once per login. */
export function loadAskHistory() {
  if (!loaded) {
    const mine = generation;
    loaded = fetchPage({ limit: FIRST_PAGE }).catch(() => {
      if (mine !== generation) return;
      loaded = null;                                // try again next time the tab opens
      setState(() => ({ historyError: "Your earlier questions couldn't be loaded." }));
    });
  }
  return loaded;
}

/** "Show more": the next PAGE_SIZE saved answers, older than the oldest already listed. */
export async function loadMoreAskHistory() {
  if (state.loadingMore || !state.hasMore) return;
  const ids = [...state.answers, ...state.previous].map((a) => a.history_id).filter(Boolean);
  const mine = generation;
  setState(() => ({ loadingMore: true }));
  try {
    await fetchPage({ limit: PAGE_SIZE, before: Math.min(...ids) });
  } catch {
    if (mine === generation) setState(() => ({ historyError: "More questions couldn't be loaded - try again." }));
  } finally {
    if (mine === generation) setState(() => ({ loadingMore: false }));
  }
}

/** Opens a previous answer in full, at the top, as it was saved (no new question is asked). */
export function openPrevious(id) {
  setState((s) => {
    const picked = s.previous.find((a) => a.id === id);
    if (!picked) return {};
    return { previous: s.previous.filter((a) => a.id !== id), answers: [picked, ...s.answers] };
  });
}

/** Asks (body = { question }) or refines an existing answer in place (replaceId + { question, query, filters }). */
export async function runAsk(body, replaceId) {
  const id = replaceId ?? nextId++;
  const replaced = replaceId ? state.answers.find((a) => a.id === replaceId) : null;
  const request = replaced?.history_id ? { ...body, history_id: replaced.history_id } : body;
  setState((s) => ({
    busy: true,
    answers: replaceId
      ? s.answers.map((a) => (a.id === id ? { ...a, pending: true } : a))
      : [{ id, question: body.question, pending: true }, ...s.answers].slice(0, MAX_ANSWERS),
  }));
  let result;
  try {
    result = { ...(await api.ask(request)), id };
  } catch (e) {
    const unavailable = e instanceof ApiError && e.status === 503;
    result = { id, question: body.question, status: "error", message: unavailable ? "Ask a question isn't available right now - the model server isn't running." : e.message };
  }
  setState((s) => ({ busy: false, answers: s.answers.map((a) => (a.id === id ? { ...a, ...result, pending: false } : a)) }));
}

/** Empties this browser's copy only (login and logout); the saved list stays on the server. */
export function resetAskHistory() {
  generation += 1;
  loaded = null;
  setState(() => EMPTY);
}

/** "Clear these answers": deletes the user's saved list as well. */
export async function clearAskHistory() {
  resetAskHistory();
  loaded = Promise.resolve();                       // nothing left to load for this login
  try {
    await api.clearAskHistory();
  } catch {
    loaded = null;                                  // not deleted on the server: they come back on reload
  }
}
