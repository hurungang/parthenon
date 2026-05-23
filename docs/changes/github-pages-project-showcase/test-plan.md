# Test Plan: GitHub Pages Project Showcase

Created by: Tester Agent  
Date: 2026-05-22  
Status: Implemented

## 1. Test Strategy

This change introduces a static project showcase website and GitHub Pages deployment pipeline. Testing focuses on validating build output, static-site functionality, content accuracy, and deployment reliability.

Primary strategy:
- Verify local static build succeeds and emits deployable artifacts to `docs/`.
- Verify the generated site is functionally correct (navigation, tab behavior, diagram rendering, responsive layout).
- Verify content correctness against architecture expectations in product documentation (three-service decomposition, permissions model, dual identity model).
- Verify screenshot placeholders exist in all required walkthrough panels and are clearly labeled as placeholders.
- Verify GitHub Actions workflow validity and successful deployment behavior for pushes to `main`.
- Verify prototype usability as static files (`file://`) for local demonstration use.

Test layers:
- E2E tests in `e2e/tests/` for functional behavior and responsive checks.
- CI workflow validation for `.github/workflows/deploy-github-pages.yml` and deployment outcomes.
- Manual/visual verification for rendered diagram fidelity and content wording accuracy.

Out-of-scope for this change:
- Backend tests (`backend/tests/`) are not required.
- Frontend unit tests (`frontend/src/__tests__/`) are not required.

## 2. Coverage Areas

1. Build Output and Artifact Location
- Validate `npm run build` succeeds in `site/` with no build errors.
- Validate static output is generated into repository-root `docs/`.
- Validate generated assets are complete and internally referenced via relative paths suitable for Pages hosting.

2. Global Navigation and Section Access
- Validate sticky navigation renders and remains usable while scrolling.
- Validate all in-page navigation links smooth-scroll to the correct section.
- Validate no broken anchor targets.

3. Architecture Section Accuracy and Completeness
- Validate four architecture cards are visible and readable.
- Validate each card reflects the intended platform architecture narrative and does not contradict core platform decomposition.

4. Mermaid Diagram Rendering
- Validate Mermaid content renders into a visible, legible diagram.
- Validate rendering is not an empty container, blank box, or raw diagram source text.

5. Security Section Coverage
- Validate three security cards are visible.
- Validate card titles and descriptions align with platform security concepts presented in PRD/spec.

6. Demo Tabs and Panel Switching
- Validate five demo tabs are present.
- Validate selecting each tab activates only its corresponding panel and hides non-active panels.
- Validate default tab state is consistent and content is visible without errors.

7. Placeholder Image Presence and Labeling
- Validate all five demo tab panels include a placeholder image.
- Validate placeholder labels/captions clearly indicate placeholders and the intended UI context.
- Validate no missing image assets or broken image references.

8. Mobile Responsiveness
- Validate layout adapts correctly at viewport widths less than or equal to 768px.
- Validate navigation, cards, tabs, and image blocks remain readable and usable on mobile.

9. Offline/Local Prototype Behavior (`file://`)
- Validate generated static files open and function as prototype content from local filesystem.
- Validate key interactions (anchors/tabs/diagram where supported by local execution context) remain usable enough for prototype review.

10. GitHub Actions Pipeline and Deployment
- Validate workflow YAML is syntactically valid and uses expected Pages actions.
- Validate push to `main` triggers build and deployment jobs.
- Validate deployment succeeds when Pages is configured for GitHub Actions.
- Validate site becomes accessible at Pages URL post-deployment.

## 3. Critical Scenarios (WHEN/THEN)

1. Build success and output path
- WHEN a contributor runs the production build in `site/`
- THEN the build completes successfully and outputs deployable files into `docs/`.

2. Sticky navigation behavior
- WHEN a visitor scrolls through the page
- THEN the top navigation remains sticky and usable for section jumps.

3. Smooth-scroll anchors
- WHEN a visitor clicks any section link in the navigation
- THEN the page smoothly scrolls to the intended section and section content is visible.

4. Architecture card completeness
- WHEN the Architecture section is loaded
- THEN exactly four architecture cards are visible with expected headings and descriptive content.

5. Mermaid rendering quality
- WHEN the page initializes the diagram section
- THEN the Mermaid diagram renders as structured nodes/edges and not as a blank box.

6. Security card completeness
- WHEN the Security section is viewed
- THEN exactly three security cards are visible with readable, relevant content.

7. Demo tab switching
- WHEN a visitor selects each of the five demo tabs one by one
- THEN only the selected tab panel is displayed and all other panels are hidden.

8. Placeholder image verification
- WHEN each demo tab panel is active
- THEN one labeled placeholder image is present, visible, and clearly marked as a placeholder.

9. Mobile layout adaptation
- WHEN the viewport is resized to 768px or below
- THEN navigation, cards, and tab panels reflow into a mobile-friendly layout with no clipped critical content.

10. GitHub Actions deployment on push
- WHEN a commit touching site content is pushed to `main`
- THEN the GitHub Actions workflow runs build and deploy jobs successfully and publishes the updated site.

## 4. Edge Cases and Risks

1. JavaScript disabled
- Risk: Interactive features (smooth-scroll enhancements, tab switching, Mermaid rendering) may degrade.
- Validation: Verify baseline readability and content discoverability with JS disabled; document expected non-interactive limitations.

2. Mermaid CDN unavailable
- Risk: External dependency outage could break diagram rendering.
- Validation: Confirm Mermaid is bundled in build output and does not depend on runtime CDN availability.

3. First push before Pages is enabled
- Risk: Deployment job may fail despite valid workflow.
- Validation: Confirm repository Pages source is configured to GitHub Actions before declaring pipeline failure as product defect.

4. Relative path regressions
- Risk: Incorrect base path breaks assets on `<org>.github.io/<repo>` subpaths.
- Validation: Verify built site resolves CSS/JS/images under subpath hosting.

5. Broken placeholder asset references
- Risk: Missing placeholder SVGs create broken image icons in demo panels.
- Validation: Verify all five expected placeholder files are present in output and linked correctly.

## 5. Acceptance Criteria Checklist

The checklist below mirrors PRD acceptance criteria and maps each item to explicit verification.

### Site Publishing
- [ ] Site is accessible at the project GitHub Pages URL after merge to `main`.
- [ ] GitHub Actions workflow automatically builds and publishes on every push to `main`.
- [ ] Site loads correctly in modern browsers (Chrome, Firefox, Safari, Edge) without blocking errors.

### High-Level Design Section
- [ ] Dedicated section explains SOP/Skill-driven MCP integration architecture.
- [ ] Tools permission control is explained in business-readable language through skills, roles, and agent identities.
- [ ] Three-service backend decomposition is clearly communicated: Control Center, Communication Hub, Agent Runtime, including responsibilities.
- [ ] Dual-identity model (human realm and agent realm) is explained with purpose of separation.
- [ ] Architectural diagrams render from source with no external image dependency.

### Demo / Walkthrough Section
- [ ] Dedicated walkthrough section includes all five required topics:
- [ ] Integrating an MCP server.
- [ ] Creating Skills and SOPs.
- [ ] Creating Agent Roles.
- [ ] Creating Agent Types and triggering agents (non-conversational and conversational).
- [ ] Viewing execution logs.
- [ ] Each walkthrough page/panel describes workflow steps in logical user-oriented order.
- [ ] Screenshot references are represented by clearly labeled placeholder images.

### Presentation Quality
- [ ] Visual presentation is modern and polished for professional showcase use.
- [ ] Site is fully navigable as static HTML/CSS/JS with no backend dependency.
- [ ] Site is responsive and readable on desktop and mobile sizes.
- [ ] No broken links or missing assets across all sections.

### Build & Deployment
- [ ] Build step is automated in GitHub Actions workflow.
- [ ] Build produces a static output folder directly servable by GitHub Pages.
- [ ] Site has no server-side runtime dependency.

## 6. Test File References

Based on `docs/config.yaml` `source.tests` paths, this change should use:

- Backend: `backend/tests/unit/test_github_pages_showcase_site.py`
- Frontend: `frontend/src/__tests__/service-decomposition/github-pages-showcase.test.ts`
- E2E: `e2e/tests/github-pages-showcase.spec.ts`
- E2E config for showcase runner: `e2e/playwright.showcase.config.ts`

## 7. Execution Notes

- Use `site/` as working directory for local build and preview verification.
- Validate generated `docs/` output as the deployment artifact target.
- For CI verification, capture workflow run status and deployment URL evidence.