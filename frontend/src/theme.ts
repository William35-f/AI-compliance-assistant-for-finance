import { useEffect, useState } from "react";

// Light is the default. The reader's choice is remembered in this browser only; storage can
// be blocked (private windows, strict settings), so every access is guarded and the app
// still works, just without remembering. index.html applies the saved theme before the
// first paint so the page doesn't flash light first.
export type Theme = "light" | "dark";

const KEY = "regulens-theme";
const THEME_COLOR: Record<Theme, string> = { light: "#F6F7F4", dark: "#000000" };

function savedTheme(): Theme {
  try {
    return window.localStorage.getItem(KEY) === "dark" ? "dark" : "light";
  } catch {
    return "light";
  }
}

export function useTheme(): [Theme, (theme: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(savedTheme);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", THEME_COLOR[theme]);
    try {
      window.localStorage.setItem(KEY, theme);
    } catch {
      /* not remembered; fine */
    }
  }, [theme]);

  return [theme, setTheme];
}
