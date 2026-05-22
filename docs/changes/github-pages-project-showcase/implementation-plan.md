## Overview

Build a polished static GitHub Pages showcase site for Parthenon using Vite + vanilla TypeScript. Source lives in `site/` at the repo root; the build outputs to `docs/` for GitHub Pages serving. A GitHub Actions workflow automatically builds and publishes on every push to `main`.

## Task Checklist

### Phase 1 — Site Scaffolding
- [ ] 1.1 — Create `site/` directory structure
- [ ] 1.2 — Create `site/package.json` with Vite + TypeScript + Mermaid dependencies
- [ ] 1.3 — Create `site/tsconfig.json`
- [ ] 1.4 — Create `site/vite.config.ts` with output dir set to `../docs` and correct base path
- [ ] 1.5 — Create `site/index.html` shell (links to `src/main.ts`, preserves prototype nav/section structure)

### Phase 2 — Content & Sections
- [ ] 2.1 — Port hero section from prototype into `site/index.html` (badge, title, tagline, service pills)
- [ ] 2.2 — Port architecture section (four arch-cards: SOP/Skill MCP, Security & Permissions, Three-Service Isolation, Dual Identity)
- [ ] 2.3 — Port diagram section with Mermaid flowchart source inline
- [ ] 2.4 — Port security deep-dive section (three sec-cards: Tool-Level Permissions, mTLS, Token Isolation)
- [ ] 2.5 — Port demo/walkthroughs section with all five tab panels (MCP, Skill/SOP, Agent Roles, Agent Types & Trigger, Execution Logs)
- [ ] 2.6 — Port footer section
- [ ] 2.7 — Create `site/src/main.ts` — entry point that imports and initialises all modules
- [ ] 2.8 — Create `site/src/tabs.ts` — tab switching logic (pill click → show/hide panels, active state)
- [ ] 2.9 — Create `site/src/animations.ts` — IntersectionObserver fade-up animation for `.fade-up` elements
- [ ] 2.10 — Create `site/src/mermaid-init.ts` — import and initialise Mermaid with dark theme config

### Phase 3 — Placeholder Assets
- [ ] 3.1 — Create `site/public/images/placeholder-mcp.svg` (MCP Server Registration UI placeholder)
- [ ] 3.2 — Create `site/public/images/placeholder-skill-sop.svg` (Skill & SOP UI placeholder)
- [ ] 3.3 — Create `site/public/images/placeholder-agent-roles.svg` (Agent Roles UI placeholder)
- [ ] 3.4 — Create `site/public/images/placeholder-agent-trigger.svg` (Agent Types & Trigger UI placeholder)
- [ ] 3.5 — Create `site/public/images/placeholder-exec-logs.svg` (Execution Logs UI placeholder)
- [ ] 3.6 — Replace inline `screenshot-placeholder` divs in `index.html` with `<img>` tags pointing to SVG files

### Phase 4 — Build Pipeline
- [ ] 4.1 — Create `.github/workflows/deploy-github-pages.yml` with build + deploy steps
- [ ] 4.2 — Enable GitHub Pages in repository settings (document manual step for operator)

### Phase 5 — Verification
- [ ] 5.1 — Run `npm run build` locally in `site/` and verify `docs/` output is produced without errors
- [ ] 5.2 — Open `docs/index.html` in browser and verify all sections render correctly
- [ ] 5.3 — Verify Mermaid diagram renders (no CDN dependency in built output)
- [ ] 5.4 — Verify all five demo tabs switch correctly
- [ ] 5.5 — Verify fade-up animations fire on scroll
- [ ] 5.6 — Verify placeholder SVGs are visible and clearly labelled in each tab panel
- [ ] 5.7 — Verify responsive layout on mobile viewport (nav collapses, grids stack)

## Phase 1 — Site Scaffolding

### 1.1 — Create `site/` directory structure

Create the following directory skeleton:

```
site/
├── package.json
├── tsconfig.json
├── vite.config.ts
├── index.html
├── src/
│   ├── main.ts
│   ├── tabs.ts
│   ├── animations.ts
│   └── mermaid-init.ts
└── public/
    └── images/
        ├── placeholder-mcp.svg
        ├── placeholder-skill-sop.svg
        ├── placeholder-agent-roles.svg
        ├── placeholder-agent-trigger.svg
        └── placeholder-exec-logs.svg
```

**Done when:** All directories exist and the repository tree matches the structure above.

---

### 1.2 — Create `site/package.json`

Declare `vite`, `typescript`, and `mermaid` as dependencies. Add `build` script (`vite build`) and `dev` script (`vite`).

**Done when:** `npm install` completes without errors inside `site/`.

---

### 1.3 — Create `site/tsconfig.json`

Standard browser TypeScript config targeting ES2020, `moduleResolution: bundler`, `strict: true`.

**Done when:** File exists and `tsc --noEmit` reports no errors.

---

### 1.4 — Create `site/vite.config.ts`

Configure:
- `build.outDir: '../docs'` — output goes to repo-root `docs/` for GitHub Pages
- `build.emptyOutDir: true` — clean output on each build
- `base: './'` — relative base path so GitHub Pages serves correctly whether at root or subdirectory

**Done when:** `npm run build` writes to `docs/` without errors.

---

### 1.5 — Create `site/index.html` shell

Vite entry HTML file. Includes:
- Font preconnects (Google Fonts: Inter + Fira Code)
- All CSS (ported from prototype `<style>` block verbatim)
- `<script type="module" src="/src/main.ts"></script>` in `<body>`
- Section placeholders ready for Phase 2 content population

**Done when:** `npm run dev` serves the page and the nav bar renders.

---

## Phase 2 — Content & Sections

### 2.1 — Port hero section

Copy hero HTML from prototype into `site/index.html`. Includes badge, title with gradient span, tagline, description, CTA button, and service pills (Control Center, Communication Hub, Agent Runtime).

**Done when:** Hero section is visible with correct layout and gradient title.

---

### 2.2 — Port architecture section

Copy the four `.arch-card` elements from prototype. Cards cover: SOP/Skill-Driven MCP Integration, Security & Permission Control, Three-Service Isolation, Dual Identity Support.

**Done when:** Four cards render in a 2×2 grid with icons, titles, and bullet lists.

---

### 2.3 — Port diagram section

Copy Mermaid flowchart source block (the `%%{init: ...}%%` flowchart) into `index.html` inside a `.diagram-wrap` container. Mermaid is initialised from `mermaid-init.ts` (not CDN).

**Done when:** Architecture diagram renders from bundled Mermaid with no CDN requests.

---

### 2.4 — Port security deep-dive section

Copy the three `.sec-card` elements: Tool-Level Permission Control, mTLS Certificate Authentication, Token Isolation.

**Done when:** Three cards render with gradient top-border, icon, description, and `sec-tag`.

---

### 2.5 — Port demo/walkthroughs section with all five tabs

Copy all five tab panels from prototype:
1. **MCP Server** — 4 steps (Register, Sync Tools, Configure Sessions, Test Connectivity) + placeholder image
2. **Skill & SOP** — 4 steps (Define Skill, Compose SOP, Review Tool Allow-List, Test SOP) + placeholder image
3. **Agent Roles** — 4 steps (Create Role, Assign SOPs/Skills, Bind Agent Identity, Validate Allow-List) + placeholder image
4. **Agent Types & Trigger** — sub-columns for non-conversational and conversational modes + placeholder image
5. **Execution Logs** — 3 steps (Navigate to Session, Inspect Span Tree, Toggle Raw Logs) + placeholder image

**Done when:** All five tab panels have correct step content and placeholder image slots.

---

### 2.6 — Port footer section

Copy footer with logo, tagline, GitHub and docs links, and license note.

**Done when:** Footer renders at page bottom with correct styling.

---

### 2.7 — Create `site/src/main.ts`

Entry point that imports `initTabs`, `initAnimations`, and `initMermaid`, calling each on `DOMContentLoaded`.

**Done when:** TypeScript compiles and all three init functions are called in the browser.

---

### 2.8 — Create `site/src/tabs.ts`

Export `initTabs()`. Queries all `.tab-pill` buttons and `.tab-panel` elements. On pill click: remove `active` from all pills and panels, add `active` to clicked pill and the panel whose `id` matches `data-tab` attribute.

**Done when:** Clicking each tab pill shows only that tab's panel; active pill is highlighted.

---

### 2.9 — Create `site/src/animations.ts`

Export `initAnimations()`. Creates an `IntersectionObserver` with `threshold: 0.12`. Observes all `.fade-up` elements. On intersection, adds `visible` class (CSS handles opacity/transform transition).

**Done when:** Elements with `.fade-up` animate in as the user scrolls down the page.

---

### 2.10 — Create `site/src/mermaid-init.ts`

Export `initMermaid()`. Imports `mermaid` from the `mermaid` npm package. Calls `mermaid.initialize()` with the same dark theme config as the prototype (`theme: 'dark'`, themeVariables matching prototype colours). Calls `mermaid.run()` to render `.mermaid` elements.

**Done when:** Mermaid diagram renders from bundled package with no CDN script tag.

---

## Phase 3 — Placeholder Assets

### 3.1–3.5 — Create SVG placeholder images

Each SVG is a self-contained rectangle (800×500) with:
- Dark background matching site palette (`#161d35`)
- Dashed border in accent colour (`#7c5cfc`)
- Centered text: camera emoji + descriptive name (e.g., "MCP Server Registration UI") + italic note "Replace with actual screenshot"
- Monospace filename label in accent colour

One file per demo tab:
- `placeholder-mcp.svg` — "MCP Server Registration UI"
- `placeholder-skill-sop.svg` — "Skill & SOP Configuration UI"
- `placeholder-agent-roles.svg` — "Agent Roles Management UI"
- `placeholder-agent-trigger.svg` — "Agent Types & Trigger UI"
- `placeholder-exec-logs.svg` — "Execution Logs Viewer"

**Done when:** All five SVG files exist and display correctly as `<img>` elements in a browser.

---

### 3.6 — Replace inline placeholder divs with `<img>` tags

In `site/index.html`, replace each `.screenshot-placeholder` div with:
```html
<img src="/images/placeholder-mcp.svg" alt="MCP Server Registration UI — screenshot placeholder" class="demo-screenshot" />
```
Add `.demo-screenshot { width: 100%; border-radius: var(--radius-md); }` to the CSS.

**Done when:** Each tab panel shows the correct SVG image instead of the inline div placeholder.

---

## Phase 4 — Build Pipeline

### 4.1 — Create GitHub Actions workflow

File: `.github/workflows/deploy-github-pages.yml`

Trigger: `push` to `main` branch (paths: `site/**`).

Steps:
1. `actions/checkout@v4`
2. `actions/setup-node@v4` with Node 20
3. `npm ci` in `site/` directory
4. `npm run build` in `site/` directory
5. `actions/upload-pages-artifact@v3` pointing to `docs/` directory
6. `actions/deploy-pages@v4` in a separate `deploy` job with `pages` and `id-token: write` permissions

**Done when:** Workflow file exists and passes YAML lint.

---

### 4.2 — Document GitHub Pages settings step

In a comment in the workflow file, note the one-time manual step: in repository Settings → Pages, set Source to "GitHub Actions".

**Done when:** Comment is present in workflow file.

---

## Phase 5 — Verification

### 5.1 — Local build verification

Run `npm run build` inside `site/`. Confirm `docs/index.html` is produced and contains the expected sections.

**Done when:** Build exits 0 and `docs/` contains `index.html`, bundled JS/CSS assets, and `images/` folder.

---

### 5.2–5.7 — Browser verification

Open `docs/index.html` locally (or via `vite preview`) and verify:
- All sections render with correct styling
- Mermaid diagram appears (not blank)
- All five tab pills switch content correctly
- Fade-up animations trigger on scroll
- Placeholder SVGs are visible in each tab
- Layout is responsive at 375px mobile width (nav links hidden, grids stack to single column)

**Done when:** All items above are confirmed visually with no console errors.

---

## Completion Checklist
- [ ] `site/` source directory is committed with all TypeScript modules
- [ ] `docs/` output is committed (initial build artifact checked in for GitHub Pages bootstrap)
- [ ] All five SVG placeholder images are committed to `site/public/images/`
- [ ] `.github/workflows/deploy-github-pages.yml` is committed and passes YAML lint
- [ ] Local build produces no TypeScript or Vite errors
- [ ] All five demo tabs display correct content and placeholder images
- [ ] Mermaid diagram renders from bundled package (no CDN)
- [ ] Fade-up scroll animations work
- [ ] Responsive layout verified at mobile viewport
- [ ] README or workflow comment documents the one-time GitHub Pages source setting
