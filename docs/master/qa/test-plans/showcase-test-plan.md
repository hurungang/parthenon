# Showcase Test Plan — GitHub Pages Project Showcase

Covers the static project showcase website, its build pipeline, content correctness, and deployment verification.

---

## Coverage Areas

### 1. Build Output & Artifacts

**What is tested:**
- Source files in `site/` exist and are complete (HTML entry, TypeScript modules for tabs, animations, Mermaid init)
- GitHub Actions workflow YAML is valid and references expected `actions/upload-pages-artifact` and `actions/deploy-pages` steps
- Workflow trigger targets `main` branch

**Acceptance criteria:**
- `site/index.html`, `site/src/main.ts`, `site/src/tabs.ts`, `site/src/animations.ts`, `site/src/mermaid-init.ts` all present
- `.github/workflows/deploy-github-pages.yml` exists and contains required Pages actions
- Build produces deployable static output from `site/` into repository-root `docs/`

**Test files:**
- [backend/tests/unit/test_github_pages_showcase_site.py](../../../../backend/tests/unit/test_github_pages_showcase_site.py) — `test_showcase_site_assets_and_workflow_exist`: validates source files and workflow YAML present

---

### 2. Content Correctness — Required Sections

**What is tested:**
- Index page contains all required section headings and tab anchor IDs for the five demo walkthroughs
- Architecture, security, and demo sections are represented in the HTML

**Acceptance criteria:**
- `High-Level Architecture` section heading present
- `Security Deep Dive` section heading present
- `Demo Walkthroughs` section heading present
- Five tab anchor IDs: `tab-mcp`, `tab-skill`, `tab-role`, `tab-agent`, `tab-logs`

**Test files:**
- [backend/tests/unit/test_github_pages_showcase_site.py](../../../../backend/tests/unit/test_github_pages_showcase_site.py) — `test_showcase_index_contains_required_sections`
- [frontend/src/__tests__/service-decomposition/github-pages-showcase.test.ts](../../../../frontend/src/__tests__/service-decomposition/github-pages-showcase.test.ts) — `contains architecture and walkthrough sections in site/index.html`
- [frontend/src/__tests__/service-decomposition/github-pages-showcase.test.ts](../../../../frontend/src/__tests__/service-decomposition/github-pages-showcase.test.ts) — `references all five screenshot placeholders` (skipped — validated locally)

---

### 3. E2E — Page Rendering & Tab Interaction

**What is tested:**
- Page loads and displays core section headings (Architecture, Security)
- Five demo walkthrough tabs switch correctly: clicking a tab pill activates the corresponding panel and hides others
- Placeholder images are visible in the active tab panels

**Acceptance criteria:**
- Architecture and Security headings visible on page load
- Each tab click shows only its panel (class `active` applied)
- Placeholder images present with `alt` attributes containing `placeholder`

**Test files:**
- [e2e/tests/github-pages-showcase.spec.ts](../../../../e2e/tests/github-pages-showcase.spec.ts) — `GitHub Pages showcase page > renders core sections and switches walkthrough tabs`

---

### 4. Showcase E2E Runner Configuration

**What is configured:**
- Dedicated Playwright configuration file for the showcase test suite with its own `testDir` and project settings

**Test files:**
- [e2e/playwright.showcase.config.ts](../../../../e2e/playwright.showcase.config.ts)

---

## Edge Cases & Risks

- **Mermaid CDN dependency:** Mermaid must be bundled in build output and not rely on runtime CDN availability
- **Relative path regressions:** Incorrect base path could break assets under subpath hosting (`<org>.github.io/<repo>`)
- **Placeholder image references:** Missing placeholder SVGs would create broken image icons in demo panels
- **First push before Pages enabled:** Deployment job may fail despite valid workflow if repository Pages source is not configured
- **JavaScript disabled:** Interactive features (smooth-scroll, tabs, Mermaid) may degrade; baseline readability should remain

---

## Change History

| Change | Description | Added |
|--------|-------------|-------|
| github-pages-project-showcase | Static showcase site, build pipeline, tab interactions, content validation | 2026-07-03 |
