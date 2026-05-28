// Web dashboard theme templates.
//
// COMPLETELY SEPARATE from the terminal dashboard's YAML theme system
// (cli/dashboard/themes/*.yaml). The terminal renders Textual CSS from
// YAML; the web is HTML/CSS, so its themes are CSS-variable presets
// declared in globals.css and selected at runtime by `data-theme`.
//
// Each template maps to:
//   - a `mode` (light | dark) → drives the `.dark` class (Tailwind
//     `dark:` variants + the dot-grid background)
//   - a token block in globals.css under `[data-theme="<id>"]`
//     (except `light`/`dark`, which use `:root` / `.dark` directly)
//   - a 3-color `swatch` rendered in the Settings picker
//
// Adding a template: append here + add the matching
// `[data-theme="<id>"]` block in globals.css. The picker is data-driven
// off this list, so no component edits needed.

export type ThemeMode = "light" | "dark";

export interface ThemeDef {
  id: string;
  label: string;
  description: string;
  mode: ThemeMode;
  /** Representative colors for the picker preview chip. */
  swatch: { bg: string; surface: string; accent: string; fg: string };
}

export const THEMES: ThemeDef[] = [
  {
    id: "light",
    label: "Light",
    description: "Warm paper-cream, near-monochrome",
    mode: "light",
    swatch: { bg: "#f9f8f4", surface: "#f2f0ea", accent: "#7c3aed", fg: "#1c1a16" },
  },
  {
    id: "dark",
    label: "Dark",
    description: "Deep cool charcoal — the ex-machina default",
    mode: "dark",
    swatch: { bg: "#15171f", surface: "#1b1d27", accent: "#8b5cf6", fg: "#dbd7cc" },
  },
  {
    id: "nocturne",
    label: "Nocturne",
    description: "Near-black glass with a luminous teal accent",
    mode: "dark",
    swatch: { bg: "#0b0e14", surface: "#11151f", accent: "#5eead4", fg: "#dbe2ee" },
  },
  {
    id: "mocha",
    label: "Mocha",
    description: "Soothing dark pastel with a Mauve accent",
    mode: "dark",
    swatch: { bg: "#1e1e2e", surface: "#181825", accent: "#cba6f7", fg: "#cdd6f4" },
  },
];

export const DEFAULT_THEME_ID = "dark";
export const THEME_STORAGE_KEY = "elophanto-theme";

export function getThemeDef(id: string | null | undefined): ThemeDef {
  return (
    THEMES.find((t) => t.id === id) ??
    THEMES.find((t) => t.id === DEFAULT_THEME_ID)!
  );
}

/**
 * Apply a theme to the document root: toggle the `.dark` class for the
 * theme's mode and set `data-theme` for non-default templates (light /
 * dark resolve via `:root` / `.dark` and carry no data-theme).
 */
export function applyTheme(id: string): void {
  const def = getThemeDef(id);
  const root = document.documentElement;
  root.classList.toggle("dark", def.mode === "dark");
  if (def.id === "light" || def.id === "dark") {
    root.removeAttribute("data-theme");
  } else {
    root.setAttribute("data-theme", def.id);
  }
}
