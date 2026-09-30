import { createContext, useContext } from "react";

// Clicking a menu tab reloads its page with fresh data, even the page you're on: App gives the pages a new
// start (a new key) each time a menu link is clicked. Only menu clicks count - a page that keeps its
// filters in the URL (Portfolio, Branch & segment) isn't reloaded when a filter changes.
export const PageRefreshContext = createContext(() => {});

export function usePageRefresh() {
  return useContext(PageRefreshContext);
}
