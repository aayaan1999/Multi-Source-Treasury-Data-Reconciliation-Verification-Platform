// Theme: "system" (follow the OS), "light" or "dark". Stored per browser; the CSS reads data-theme.
const KEY = "bdp_theme";

export function getTheme() {
  try {
    return localStorage.getItem(KEY) || "system";
  } catch {
    return "system";
  }
}

export function setTheme(theme) {
  try {
    localStorage.setItem(KEY, theme);
  } catch {
    /* ignore */
  }
  applyTheme(theme);
}

function applyTheme(theme) {
  const root = document.documentElement;
  if (theme === "light" || theme === "dark") root.setAttribute("data-theme", theme);
  else root.removeAttribute("data-theme");
}

export function applyStoredTheme() {
  applyTheme(getTheme());
}

export const THEME_ORDER = ["system", "light", "dark"];
