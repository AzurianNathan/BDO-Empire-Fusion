/*
 * theme.css - applies the Empire Optimizer look to every page of the map.
 *
 * Loaded after Workerman's own main.css, so it wins on equal specificity.
 *
 * Strategy, in order of preference:
 *   1. Redefine Workerman's semantic variables (--color-background, --color-text,
 *      --color-border, ...). base.css already drives body/headings/borders from
 *      these, so most of the app re-themes itself.
 *   2. Override the few hard-coded values (the green link colour, lightgray table
 *      borders).
 *   3. Restyle nav/controls/tables directly. App.vue uses <style scoped>, which
 *      adds a [data-v-*] attribute and raises specificity, so those rules are
 *      prefixed with #app to outrank them without resorting to !important.
 *
 * The design tokens are the same ones the standalone panel uses, so the two
 * surfaces stay in sync.
 */

:root {
  /* Empire Optimizer palette */
  --ink: #14110c;
  --panel: #1e1a12;
  --panel2: #241f16;
  --line: #3a3123;
  --parch: #e9ddc4;
  --muted: #9a8f79;
  --brass: #c8a24c;
  --brass2: #e6c169;
  --jade: #4c9e86;
  --danger: #c9604e;
  --silver: #d6dcea;

  /* remap Workerman's semantic variables onto it */
  --color-background: var(--ink);
  --color-background-soft: var(--panel);
  --color-background-mute: var(--panel2);
  --color-border: var(--line);
  --color-border-hover: var(--brass);
  --color-heading: #f3ead4;
  --color-text: var(--parch);
  --color-button: var(--parch);
}

/* Force the dark palette even when the OS prefers light: base.css flips these
   under a prefers-color-scheme media query, which would otherwise undo us. */
@media (prefers-color-scheme: light) {
  :root {
    --color-background: var(--ink);
    --color-background-soft: var(--panel);
    --color-background-mute: var(--panel2);
    --color-border: var(--line);
    --color-heading: #f3ead4;
    --color-text: var(--parch);
    --color-button: var(--parch);
  }
}

body {
  background: var(--ink);
  color: var(--parch);
  font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}

#app {
  max-width: 1500px;
}

/* --- typography ----------------------------------------------------------- */

h1, h2, h3, h4 {
  font-family: "Iowan Old Style", Georgia, "Times New Roman", serif;
  color: var(--color-heading);
  font-weight: 600;
  letter-spacing: 0.01em;
}

h1 { font-size: 22px; }
h2 { font-size: 17px; }
h3 { font-size: 15px; }

/* Numbers are the point of this app: line them up. */
td.num, .num, td:has(> input[type="number"]) {
  font-family: ui-monospace, "SFMono-Regular", Menlo, Consolas, monospace;
  font-variant-numeric: tabular-nums;
}

a, .green {
  color: var(--brass2);
  text-decoration: none;
  transition: color 0.15s;
}

a:hover, .green:hover {
  color: var(--brass);
  background-color: transparent;
}

/* --- top navigation ------------------------------------------------------- */
/* #app prefixes outrank App.vue's scoped [data-v-*] rules. */

#app header {
  border-bottom: 1px solid var(--line);
  margin-bottom: 14px;
}

#app nav {
  text-align: left;
  font-size: 13px;
  margin-bottom: 0;
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
}

#app nav a {
  display: inline-block;
  padding: 9px 15px;
  border: 0;
  border-bottom: 2px solid transparent;
  color: var(--muted);
  letter-spacing: 0.02em;
}

#app nav a:hover {
  color: var(--parch);
  background: rgba(200, 162, 76, 0.06);
}

#app nav a.router-link-exact-active {
  color: var(--brass2);
  border-bottom-color: var(--brass);
  background: transparent;
}

#app nav a:focus-visible {
  outline: 2px solid var(--brass);
  outline-offset: -2px;
}

/* --- tables (this app is mostly tables) ----------------------------------- */

table {
  border-collapse: collapse;
  background: var(--panel);
  border-radius: 8px;
  overflow: hidden;
}

tr, td, th {
  border: 1px solid var(--line);
  padding: 3px 7px;
}

th {
  background: var(--panel2);
  color: var(--muted);
  font-weight: 500;
  font-size: 11px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  text-align: left;
}

tbody tr:hover td {
  background: rgba(200, 162, 76, 0.05);
}

.borderless tr, .borderless td, .borderless th {
  border: none;
  background: transparent;
}

/* --- form controls -------------------------------------------------------- */

input, select, textarea, button {
  font-family: inherit;
  font-size: 13px;
}

input[type="text"], input[type="number"], input[type="search"], select, textarea {
  background: var(--ink);
  color: var(--parch);
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 4px 7px;
}

input[type="text"]:focus, input[type="number"]:focus,
input[type="search"]:focus, select:focus, textarea:focus {
  outline: none;
  border-color: var(--brass);
}

input[type="checkbox"], input[type="radio"] {
  accent-color: var(--brass);
}

button {
  background: var(--panel2);
  color: var(--parch);
  border: 1px solid var(--line);
  border-radius: 7px;
  padding: 5px 12px;
  cursor: pointer;
  transition: border-color 0.15s;
}

button:hover:not(:disabled) { border-color: var(--brass); }
button:disabled { opacity: 0.45; cursor: not-allowed; }
button:focus-visible { outline: 2px solid var(--brass); outline-offset: 2px; }

/* --- misc ----------------------------------------------------------------- */

hr { border: 0; border-top: 1px solid var(--line); }

::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: var(--ink); }
::-webkit-scrollbar-thumb { background: var(--line); border-radius: 5px; }
::-webkit-scrollbar-thumb:hover { background: var(--brass); }

/* Node/region art is drawn on light backgrounds in places; keep it legible
   rather than letting it glare against the dark panel. */
img.icon, .icon img { filter: saturate(0.92); }

@media (prefers-reduced-motion: reduce) {
  a, button, input, select { transition: none; }
}
