# apply-material-theme — Test Plan

## 1. Test Strategy

The testing approach for the Material UI theme change combines the following layers:
- **Visual Regression Testing:** Automated screenshot comparison to detect unintended visual changes across the UI.
- **Component Testing:** Validate that all key Material-UI components (AppBar, Drawer, Button, Card, etc.) render with the correct theme, styles, and overrides.
- **E2E Testing:** Simulate real user flows to ensure theme consistency, visual polish, and accessibility across the application.
- **Accessibility Testing:** Automated and manual checks to ensure color contrast, focus indicators, and keyboard navigation meet accessibility standards.
- **Cross-Browser/Device Testing:** Verify theme appearance and typography consistency across major browsers and screen sizes.

## 2. Coverage Areas

- **Theme Application:** 
  - Global application of the Material theme (palette, typography, shadows, border radius).
  - Consistent use of Inter font throughout the UI.
- **Component Styling:**
  - AppBar, Drawer, Button, Card, and all overridden components reflect the new theme (colors, radius, shadows).
  - No visual regressions or inconsistencies in custom or third-party components.
- **Color Palette:**
  - Primary color: Indigo (#4f46e5).
  - Slate/neutral palette for backgrounds and surfaces.
- **Typography:**
  - Inter font applied globally; no Roboto or fallback fonts visible.
  - Font weights, sizes, and line heights match design spec.
- **Shadows & Elevation:**
  - Refined, consistent shadow styles on all elevated surfaces (cards, dialogs, menus).
- **Border Radius:**
  - 12px border radius on cards and other relevant components.
- **Accessibility:**
  - Sufficient color contrast for text and interactive elements.
  - Focus states visible and accessible.
  - Keyboard navigation and screen reader compatibility.

## 3. Critical Scenarios

- **WHEN** the application loads  
  **THEN** the Inter font is used globally, and all components reflect the new color palette and theme.
- **WHEN** a user interacts with AppBar, Drawer, Button, and Card components  
  **THEN** each component displays the correct colors, border radius, and shadows as per the theme.
- **WHEN** a user navigates through all major pages and dialogs  
  **THEN** the theme is applied consistently, with no visual regressions or legacy styles.
- **WHEN** a user hovers, focuses, or clicks interactive elements  
  **THEN** visual feedback (hover, focus, active states) matches the refined Material theme and is accessible.
- **WHEN** the application is viewed on different browsers and devices  
  **THEN** the theme, typography, and component styles remain consistent.
- **WHEN** accessibility tools (screen readers, keyboard navigation) are used  
  **THEN** all themed components remain accessible and meet WCAG color contrast requirements.

## 4. Edge Cases & Risks

- Incomplete or partial theme application (legacy styles leaking through).
- Fallback to Roboto or system fonts due to font loading issues.
- Inconsistent border radius or shadows on custom/third-party components.
- Color contrast failures, especially in disabled or secondary states.
- Visual regressions in rarely used dialogs, modals, or error pages.
- Accessibility regressions (e.g., invisible focus outlines, insufficient contrast).
- Browser-specific rendering issues (font smoothing, color differences).

## 5. Acceptance Criteria Checklist

- [x] Inter font is applied globally; Roboto is not used anywhere.
- [x] Primary color is indigo (#4f46e5); slate/neutral palette is used for backgrounds.
- [x] All cards and relevant components have a 12px border radius.
- [x] Shadows are refined and consistent across all elevated surfaces.
- [x] AppBar, Drawer, Button, Card, and other overridden components match the design spec.
- [x] No visual regressions or legacy styles remain.
- [x] All theme changes are accessible (color contrast, focus states, keyboard navigation).
- [x] Theme is consistent across all browsers and devices.

## 6. Test File References

**Frontend Component Tests:**
- [frontend/src/__tests__/theme.spec.tsx](frontend/src/__tests__/theme.spec.tsx) — Theme configuration tests (palette, typography, shadows, component overrides) — **8/8 passed**

**E2E Tests:**
- [e2e/tests/theme-application.spec.ts](e2e/tests/theme-application.spec.ts) — Global theme application (Inter font, indigo colors, backgrounds) — **3/3 passed**
- [e2e/tests/component-theming.spec.ts](e2e/tests/component-theming.spec.ts) — Component styling (cards, AppBar, buttons) — **3/3 passed**
- [e2e/tests/page-consistency.spec.ts](e2e/tests/page-consistency.spec.ts) — Theme consistency across all major pages — **5/5 passed**
- [e2e/tests/accessibility.spec.ts](e2e/tests/accessibility.spec.ts) — WCAG AA compliance and accessibility checks — **3/3 passed**

**Total: 22/22 tests passing** ✓
