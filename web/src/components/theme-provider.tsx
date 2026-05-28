import { createContext, useContext, useEffect, useState } from "react";

import {
  applyTheme,
  DEFAULT_THEME_ID,
  getThemeDef,
  THEME_STORAGE_KEY,
  THEMES,
  type ThemeDef,
} from "@/lib/themes";

interface ThemeContextValue {
  /** Active theme id (e.g. "dark", "nocturne", "mocha"). */
  theme: string;
  /** Full definition for the active theme. */
  themeDef: ThemeDef;
  /** All available templates (for pickers). */
  themes: ThemeDef[];
  setTheme: (id: string) => void;
  /** Advance to the next template (sidebar quick-cycle). */
  cycleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextValue>({
  theme: DEFAULT_THEME_ID,
  themeDef: getThemeDef(DEFAULT_THEME_ID),
  themes: THEMES,
  setTheme: () => {},
  cycleTheme: () => {},
});

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<string>(() => {
    if (typeof window !== "undefined") {
      return localStorage.getItem(THEME_STORAGE_KEY) || DEFAULT_THEME_ID;
    }
    return DEFAULT_THEME_ID;
  });

  useEffect(() => {
    applyTheme(theme);
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  }, [theme]);

  const setTheme = (id: string) => setThemeState(getThemeDef(id).id);

  const cycleTheme = () => {
    const idx = THEMES.findIndex((t) => t.id === theme);
    const next = THEMES[(idx + 1) % THEMES.length];
    if (next) setThemeState(next.id);
  };

  return (
    <ThemeContext.Provider
      value={{
        theme,
        themeDef: getThemeDef(theme),
        themes: THEMES,
        setTheme,
        cycleTheme,
      }}
    >
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  return useContext(ThemeContext);
}
