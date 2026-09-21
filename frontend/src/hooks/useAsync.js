import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Runs an async loader on mount and whenever `deps` change, and keeps the previous result on screen while the next one
 * loads (so a filter change never blanks the page or shifts the layout).
 *   status: "loading" (nothing yet) | "ready" | "error"
 *   refreshing: true while reloading behind an existing result
 */
export default function useAsync(loader, deps = []) {
  const [state, setState] = useState({ status: "loading", data: null, error: null, refreshing: false });
  const latest = useRef(0);

  const run = useCallback(() => {
    const ticket = ++latest.current;
    setState((s) => ({ ...s, refreshing: s.status === "ready", ...(s.status === "error" ? { status: "loading" } : {}) }));
    loader().then(
      (data) => ticket === latest.current && setState({ status: "ready", data, error: null, refreshing: false }),
      (error) => ticket === latest.current && setState((s) => ({ status: "error", data: s.data, error, refreshing: false })),
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    run();
  }, [run]);

  return { ...state, reload: run };
}
