# Tech Spec: showcase

## 1. Technical Overview

The showcase module is a fully static, dependency-light Vite + TypeScript site served via GitHub Pages. It presents Parthenon's architecture, security model, and UI screenshots in a single scrollable page with tabbed demo panels and an interactive Mermaid architecture diagram. All content is hardcoded in `site/index.html` — there are no API calls, no database queries, no backend dependencies, and no user authentication. The site is built by a GitHub Actions CI/CD pipeline on push to `main` (filtered to `site/**` path changes) and deployed to `docs/site/` by `actions/deploy-pages@v4`.

---

## 2. Component Breakdown

### Build & Deployment

| Component | Responsibility |
|-----------|----------------|
| GitHub Actions Workflow | Two-job pipeline: `build` (checkout → install → `npm run build` → upload Pages artifact) and `deploy` (Pages deployment via `actions/deploy-pages@v4`). Triggers on push to `main` with `site/**` path filter. Requires `pages: write` and `id-token: write` permissions. No external secrets. |
| npm Manifest | Declares `vite`, `typescript`, and `mermaid` as the only dependencies. Provides `dev`, `build`, and `preview` scripts. |
| Vite Config | Builds the static site to `../docs/site/` with relative base path (`./`) for GitHub Pages compatibility. `emptyOutDir: true` prevents stale asset accumulation. |
| TypeScript Config | Targets ES2020 with `moduleResolution: bundler`, strict mode enabled, includes only `src/` directory. |

### Page Shell & Content

| Component | Responsibility |
|-----------|----------------|
| `index.html` | Single-page entry shell. Vite entry point. Contains all site sections (hero, architecture, diagram, security, demo tab panels, footer). All CSS is inline. Loads `src/main.ts` as an ES module. |
| `main.ts` | App entry point. Registers a `DOMContentLoaded` handler that calls `initTabs()`, `initAnimations()`, and `initMermaid()`. No side effects at module load. |

### Interactive Behaviour

| Component | Responsibility |
|-----------|----------------|
| `tabs.ts` | Tab switching logic. Exports `initTabs()` which queries `.tab-pill` and `.tab-panel` elements, attaches event delegation on pill clicks, and toggles `active` class on pills and panels via `data-tab` attributes. |
| `animations.ts` | Scroll-triggered fade-up animations. Exports `initAnimations()` which creates an `IntersectionObserver` (threshold 0.12) that adds a `visible` class to `.fade-up` elements on intersection. Unobserves elements after the first trigger. |
| `mermaid-init.ts` | Mermaid diagram setup. Exports `initMermaid()` which imports `mermaid` from the npm package (not CDN), calls `mermaid.initialize()` with a dark theme and Parthenon colour `themeVariables`, then calls `mermaid.run()` to render `.mermaid` diagram elements. |

### Placeholder Images

| Component | Responsibility |
|-----------|----------------|
| `placeholder-mcp.svg` | Tab 1 screenshot placeholder — "MCP Server Registration UI" |
| `placeholder-skill-sop.svg` | Tab 2 screenshot placeholder — "Skill & SOP Configuration UI" |
| `placeholder-agent-roles.svg` | Tab 3 screenshot placeholder — "Agent Roles Management UI" |
| `placeholder-agent-trigger.svg` | Tab 4 screenshot placeholder — "Agent Types & Trigger UI" |
| `placeholder-exec-logs.svg` | Tab 5 screenshot placeholder — "Execution Logs Viewer" |

All placeholders are 800×500 px SVGs with dark background (`#161d35`), dashed accent border (`#7c5cfc`, `stroke-dasharray="8 4"`), a camera emoji, primary label, caption ("Replace with actual screenshot"), and a monospace filename label. They are served as static assets from `site/public/images/` and referenced via `<img>` tags in `index.html`.

### Verification Tests

| Component | Responsibility |
|-----------|----------------|
| Backend unit test | Confirms showcase source files and deployment workflow exist; validates required architecture and walkthrough markers in `site/index.html`. |
| Frontend Vitest test | Validates showcase sections and placeholder image references are present in `site/index.html`. |
| E2E Playwright test | Loads the showcase site via a dedicated Vite server on port 4174, verifies key sections are visible, and validates demo tab switching behaviour. |

---

## 3. API Endpoints

**None.** The showcase site is fully static with no server-side runtime, no API calls, and no dynamic data.

---

## 4. Data Access Patterns

**None.** All content is hardcoded in `site/index.html`. There are no database queries, no API fetches, and no user authentication. The Mermaid diagram is rendered client-side from inline source text bundled into the output HTML.

---

## 5. Code Reference Map

### Build & Deployment

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `deploy-github-pages` | workflow | Two-job CI/CD pipeline: `build` (checkout → setup Node 20 → `npm ci` → `npm run build` → upload Pages artifact from `docs/site/`) and `deploy` (Pages deployment via `actions/deploy-pages@v4`). Triggers on push to `main`, filtered to `site/**` paths. Permissions: `contents: read`, `pages: write`, `id-token: write`. No external secrets. | `.github/workflows/deploy-github-pages.yml` |
| `package.json` | config | npm manifest declaring `vite`, `typescript`, `mermaid` as only dependencies; scripts: `dev`, `build`, `preview` | `site/package.json` |
| `defineConfig` | config | Vite build config: `base: './'` (relative path for GH Pages), `build.outDir: '../docs/site'`, `build.emptyOutDir: true` | `site/vite.config.ts` |

### Page Shell & Content

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| Single-page shell | HTML | Vite entry point; contains all site sections (hero, architecture, Mermaid diagram, security, 5-tab demo panel, footer); all CSS inline; loads `src/main.ts` as ES module via `<script type="module">` | `site/index.html` |
| `main.ts` | module | App entry point; registers `DOMContentLoaded` handler that calls `initTabs()`, `initAnimations()`, `initMermaid()`; no side effects at module load | `site/src/main.ts` |

### Interactive Behaviour

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `initTabs` | function | Queries `.tab-pill` / `.tab-panel` elements; attaches event delegation on pill clicks; toggles `active` class based on `data-tab` attribute | `site/src/tabs.ts` |
| `initAnimations` | function | Creates `IntersectionObserver` (threshold 0.12); adds `visible` class to `.fade-up` elements on intersection; unobserves after first trigger | `site/src/animations.ts` |
| `initMermaid` | function | Imports `mermaid` from npm; calls `mermaid.initialize()` with dark theme + Parthenon colour `themeVariables`; calls `mermaid.run()` to render `.mermaid` elements | `site/src/mermaid-init.ts` |

### Placeholder Images

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| MCP Server Registration placeholder | SVG | 800×500 px, dark background, dashed accent border, label "MCP Server Registration UI", camera emoji, caption "Replace with actual screenshot" | `site/public/images/placeholder-mcp.svg` |
| Skill & SOP Configuration placeholder | SVG | 800×500 px, dark background, dashed accent border, label "Skill & SOP Configuration UI", camera emoji, caption "Replace with actual screenshot" | `site/public/images/placeholder-skill-sop.svg` |
| Agent Roles Management placeholder | SVG | 800×500 px, dark background, dashed accent border, label "Agent Roles Management UI", camera emoji, caption "Replace with actual screenshot" | `site/public/images/placeholder-agent-roles.svg` |
| Agent Types & Trigger placeholder | SVG | 800×500 px, dark background, dashed accent border, label "Agent Types & Trigger UI", camera emoji, caption "Replace with actual screenshot" | `site/public/images/placeholder-agent-trigger.svg` |
| Execution Logs Viewer placeholder | SVG | 800×500 px, dark background, dashed accent border, label "Execution Logs Viewer", camera emoji, caption "Replace with actual screenshot" | `site/public/images/placeholder-exec-logs.svg` |

### Verification Tests

| Symbol | Type | Description | File |
|--------|------|-------------|------|
| `test_github_pages_showcase_site` | test file | Backend layer verification: confirms source files and deployment workflow exist; validates required architecture and walkthrough markers in `site/index.html` | `backend/tests/unit/test_github_pages_showcase_site.py` |
| `github-pages-showcase.test.ts` | test file | Frontend Vitest verification: validates showcase sections and placeholder image references are present in `site/index.html` | `frontend/src/__tests__/service-decomposition/github-pages-showcase.test.ts` |
| `github-pages-showcase.spec.ts` | test file | E2E Playwright verification: loads showcase site from dedicated Vite server (port 4174), verifies key sections, validates demo tab switching behaviour | `e2e/tests/github-pages-showcase.spec.ts` |
